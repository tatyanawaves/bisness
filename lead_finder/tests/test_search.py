"""Поиск, исключение отработанных, сохранение и разбор ответов источников."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lead_finder import company, config, db, llm, maps, prospects, scripts


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def place(place_id, name, phone="+7 701 000 00 00", types=("construction_company",)):
    return {
        "id": place_id,
        "displayName": {"text": name},
        "formattedAddress": "Астана",
        "location": {"latitude": 51.17, "longitude": 71.45},
        "types": list(types),
        "internationalPhoneNumber": phone,
        "businessStatus": "OPERATIONAL",
    }


def model_answer(batch_size, size="medium", monthly="high", fit=80):
    return {
        "items": [
            {
                "i": i,
                "activity": "Строительство",
                "activity_key": "construction",
                "size": size,
                "size_why": "Несколько объектов",
                "monthly": monthly,
                "monthly_why": "Постоянно идут работы",
                "buys": ["материалы"],
                "fit": fit,
                "idea": {"product": "упаковка", "why": "Перевозят материалы"},
                "buyer": "снабженец",
            }
            for i in range(batch_size)
        ]
    }


PROFILE_ANSWER = {
    "name": "Упак-Трейд",
    "summary": "Упаковка для производств",
    "is_service": False,
    "offer_nom": "упаковка",
    "offer_gen": "упаковки",
    "offer_dat": "упаковке",
    "examples": ["гофрокартон", "плёнка"],
    "products": ["гофрокартон", "плёнка"],
    "activity_keys": ["production", "construction", "unknown_key"],
    "search_phrases": ["строительная компания"],
}


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(config, "DB_PATH", Path(self.tmp.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init_db()
        for name, value in (("GOOGLE_PLACES_API_KEY", "maps-test"), ("DGIS_API_KEY", ""), ("MAP_PROVIDER", ""), ("GROQ_API_KEY", "llm-test")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def run_search(self, pages, model=None, **params):
        """Запускает поиск с подменёнными картами и моделью, возвращает события."""
        payload = {"city": "Астана", "count": 5, "offer": "упаковка", "activities": ["construction"], **params}
        answers = iter(pages)

        def fake_post(url, **kwargs):
            if "places:searchText" in url:
                return FakeResponse(payload={"places": next(answers, [])})
            body = kwargs["json"]
            user = body["messages"][1]["content"]
            if "Список деятельности" in user and "Компании:" not in user:
                content = json.dumps(PROFILE_ANSWER, ensure_ascii=False)
            else:
                companies = json.loads(user.split("Компании: ")[1].split("\n")[0])
                content = json.dumps((model or model_answer)(len(companies)), ensure_ascii=False)
            return FakeResponse(payload={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

        with mock.patch("requests.post", side_effect=fake_post):
            return list(prospects.run_search(prospects.parse_params(payload)))


class SearchFlow(DatabaseCase):
    def test_returns_requested_count_and_saves_everything(self):
        pages = [[place(f"p{i}", f"ТОО Компания {i}") for i in range(10)]]
        events = self.run_search(pages, count=4)
        found = [e["business"] for e in events if e["type"] == "business"]
        done = next(e for e in events if e["type"] == "done")
        self.assertEqual(len(found), 4)
        self.assertEqual(done["found"], 4)
        self.assertEqual(done["requested"], 4)
        self.assertEqual(found[0]["analysis"]["size"], "medium")
        self.assertTrue(found[0]["analysis"]["is_ai"])
        with db.session() as conn:
            self.assertGreaterEqual(len(db.list_analyses(conn)), 4)

    def test_no_extra_map_pages_once_enough_companies_are_in_hand(self):
        map_calls = []

        def fake_post(url, **kwargs):
            if "places:searchText" in url:
                map_calls.append(url)
                start = int(kwargs["json"].get("pageToken") or 0)
                return FakeResponse(payload={
                    "places": [place(f"p{i}", f"ТОО Компания {i}") for i in range(start, start + 5)],
                    "nextPageToken": str(start + 5),
                })
            user = kwargs["json"]["messages"][1]["content"]
            companies = json.loads(user.split("Компании: ")[1].split("\n")[0])
            content = json.dumps(model_answer(len(companies)), ensure_ascii=False)
            return FakeResponse(payload={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

        with mock.patch("lead_finder.company.llm.chat_json", return_value=PROFILE_ANSWER):
            profile, _ = company.analyze_company("", "упаковка")
        with mock.patch("requests.post", side_effect=fake_post):
            events = list(prospects.run_search(prospects.parse_params(
                {"city": "Астана", "count": 3, "profile_id": profile["id"], "activities": ["construction"]})))
        self.assertEqual(len([e for e in events if e["type"] == "business"]), 3)
        self.assertEqual(len(map_calls), 1)

    def test_2gis_key_without_phones_is_explained_to_the_user(self):
        item = {"id": "5", "name": "ТОО Альфа", "org": {"name": "Альфа", "branch_count": 1}, "point": {"lat": 51.17, "lon": 71.45}}

        def fake_get(url, **kwargs):
            return FakeResponse(payload={"meta": {"code": 200}, "result": {"items": [item], "total": 1}})

        def fake_post(url, **kwargs):
            user = kwargs["json"]["messages"][1]["content"]
            companies = json.loads(user.split("Компании: ")[1].split("\n")[0])
            content = json.dumps(model_answer(len(companies)), ensure_ascii=False)
            return FakeResponse(payload={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

        with mock.patch("lead_finder.company.llm.chat_json", return_value=PROFILE_ANSWER):
            profile, _ = company.analyze_company("", "упаковка")
        with mock.patch.object(config, "MAP_PROVIDER", "2gis"), mock.patch.object(config, "DGIS_API_KEY", "k"), \
             mock.patch("requests.get", side_effect=fake_get), mock.patch("requests.post", side_effect=fake_post):
            events = list(prospects.run_search(prospects.parse_params(
                {"city": "Астана", "count": 1, "profile_id": profile["id"], "activities": ["construction"]})))
        found = next(e["business"] for e in events if e["type"] == "business")
        self.assertEqual(found["map_url"], "https://2gis.kz/firm/5")
        self.assertEqual(found["phones"], [])
        self.assertTrue(any(e["type"] == "warning" and "Телефоны не подключены" in e["text"] for e in events))

    def test_worked_business_never_returns_in_later_searches(self):
        pages = [[place("p1", "ТОО Альфа"), place("p2", "ТОО Бета", phone="+7 702 111 22 33")]]
        first = [e["business"] for e in self.run_search(pages) if e["type"] == "business"]
        self.assertEqual(len(first), 2)
        alfa = next(b for b in first if b["name"] == "ТОО Альфа")
        with db.session() as conn:
            db.set_worked(conn, alfa["id"], True)

        again = [e["business"]["name"] for e in self.run_search(pages) if e["type"] == "business"]
        self.assertEqual(again, ["ТОО Бета"])

    def test_worked_business_is_recognised_under_another_source_id_name_or_phone(self):
        first = self.run_search([[place("p1", "ТОО «Альфа»", phone="8 (701) 555-44-33")]])
        business = next(e["business"] for e in first if e["type"] == "business")
        with db.session() as conn:
            db.set_worked(conn, business["id"], True)

        same_name = place("other-id", "Альфа ТОО", phone="+7 700 999 99 99")
        same_phone = place("third-id", "Совсем другое имя", phone="+7 701 555 44 33")
        events = self.run_search([[same_name, same_phone]])
        self.assertEqual([e for e in events if e["type"] == "business"], [])
        self.assertEqual(next(e for e in events if e["type"] == "done")["skipped_worked"], 2)

    def test_returning_to_search_brings_business_back(self):
        pages = [[place("p1", "ТОО Альфа")]]
        business = next(e["business"] for e in self.run_search(pages) if e["type"] == "business")
        with db.session() as conn:
            db.set_worked(conn, business["id"], True)
            db.set_worked(conn, business["id"], False)
        names = [e["business"]["name"] for e in self.run_search(pages) if e["type"] == "business"]
        self.assertEqual(names, ["ТОО Альфа"])

    def test_size_filter_keeps_only_selected_sizes(self):
        pages = [[place(f"p{i}", f"ТОО Компания {i}") for i in range(6)]]
        events = self.run_search(pages, sizes=["large"], model=lambda n: model_answer(n, size="medium"))
        self.assertEqual([e for e in events if e["type"] == "business"], [])
        self.assertEqual(next(e for e in events if e["type"] == "done")["dropped"]["size"], 6)

    def test_companies_that_do_not_buy_regularly_are_dropped_by_default(self):
        pages = [[place("p1", "ТОО Альфа")]]
        events = self.run_search(pages, model=lambda n: model_answer(n, monthly="low"))
        self.assertEqual([e for e in events if e["type"] == "business"], [])

    def test_saved_ai_analysis_is_reused_without_new_model_call(self):
        pages = [[place("p1", "ТОО Альфа")]]
        calls = []

        def counting(n):
            calls.append(n)
            return model_answer(n)

        self.run_search(pages, model=counting)
        self.run_search(pages, model=counting)
        self.assertEqual(len(calls), 1)

    def test_rate_limit_falls_back_and_says_so(self):
        answers = iter([[place("p1", "ТОО Альфа", types=("construction_company",))]])

        def fake_post(url, **kwargs):
            if "places:searchText" in url:
                return FakeResponse(payload={"places": next(answers, [])})
            return FakeResponse(status=429, payload={}, headers={"retry-after": "3600"})

        with mock.patch("requests.post", side_effect=fake_post):
            events = list(prospects.run_search(prospects.parse_params(
                {"city": "Астана", "count": 3, "offer": "упаковка", "activities": ["construction"]})))
        self.assertTrue(any(e["type"] == "warning" and "лимит" in e["text"].lower() for e in events))
        found = [e["business"] for e in events if e["type"] == "business"]
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["analysis"]["is_ai"])

    def test_missing_map_key_gives_clear_error(self):
        with mock.patch.object(config, "GOOGLE_PLACES_API_KEY", ""):
            events = list(prospects.run_search(prospects.parse_params({"city": "Астана", "offer": "упаковка"})))
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("GOOGLE_PLACES_API_KEY", events[0]["text"])

    def test_invalid_params_are_rejected(self):
        for payload, message in (
            ({"city": "Москва", "offer": "x"}, "город"),
            ({"city": "Астана"}, "продать"),
            ({"city": "Астана", "offer": "x", "count": 500}, "от 1 до"),
            ({"city": "Астана", "offer": "x", "count": "много"}, "числом"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                prospects.parse_params(payload)


class ScriptGeneration(DatabaseCase):
    def _business_and_profile(self):
        events = self.run_search([[place("p1", "ТОО Альфа")]])
        business = next(e["business"] for e in events if e["type"] == "business")
        profile = next(e["profile"] for e in events if e["type"] == "profile")
        return business, profile

    def test_each_generation_is_saved_as_a_new_version(self):
        business, profile = self._business_and_profile()
        slots = {
            "secretary_question": "кто у вас закупает упаковку для объектов?",
            "process_question": "Упаковку берёте под объект или про запас?",
            "ideas": [{"product": "плёнка", "why": "Перевозят материалы", "question": "Плёнка у вас проходит через закупку?"}],
        }
        answer = FakeResponse(payload={"choices": [{"message": {"content": json.dumps(slots, ensure_ascii=False)}, "finish_reason": "stop"}]})
        with mock.patch("requests.post", return_value=answer):
            first = scripts.generate(business["id"], profile["id"], "Алия")
            second = scripts.generate(business["id"], profile["id"], "Алия")
        self.assertNotEqual(first["id"], second["id"])
        with db.session() as conn:
            self.assertEqual(len(db.list_scripts(conn)), 2)
            stored = db.get_script(conn, first["id"])
        self.assertTrue(stored["is_ai"])
        self.assertIn("кто у вас закупает упаковку для объектов?", stored["plain_text"])
        self.assertIn("Плёнка у вас проходит через закупку?", stored["plain_text"])
        self.assertIn("Алия", stored["plain_text"])

    def test_without_model_script_is_built_from_lesson_and_marked(self):
        business, profile = self._business_and_profile()
        with mock.patch.object(config, "GROQ_API_KEY", ""):
            script = scripts.generate(business["id"], profile["id"])
        self.assertFalse(script["is_ai"])
        self.assertTrue(script["content"]["warnings"])
        self.assertIn("[ваше имя]", script["plain_text"])

    def test_unknown_business_is_reported(self):
        with self.assertRaises(LookupError):
            scripts.generate(999, 1)


class MapParsing(unittest.TestCase):
    def test_2gis_item_is_normalized_from_documented_shape(self):
        item = {
            "id": "70000001087490185_abc",
            "name": "Почта, отделение №1",
            "address_name": "Ильинка улица, 9",
            "org": {"branch_count": 1208, "id": "1", "name": "Почта", "primary": "Почта"},
            "point": {"lat": 51.1, "lon": 71.4},
            "rubrics": [{"id": "192", "kind": "primary", "name": "Почтовые отделения"}],
            "contact_groups": [{"contacts": [
                {"type": "phone", "text": "+7 (495) 795-37-95", "value": "+74957953795"},
                {"type": "website", "text": "site.kz", "url": "https://site.kz", "value": "https://site.kz"},
                {"type": "email", "text": "i@site.kz", "value": "i@site.kz"},
            ]}],
        }
        biz = maps._from_dgis(item)
        self.assertEqual(biz["source_id"], "70000001087490185")
        self.assertEqual(biz["org_name"], "Почта")
        self.assertEqual(biz["branch_count"], 1208)
        self.assertEqual(biz["phones"], ["+74957953795"])
        self.assertEqual(biz["website"], "https://site.kz")
        self.assertEqual(biz["email"], "i@site.kz")
        self.assertEqual(biz["rubrics"], ["Почтовые отделения"])
        self.assertEqual(biz["map_url"], "https://2gis.kz/firm/70000001087490185")

    def test_2gis_page_size_limit_is_remembered_between_searches(self):
        limited = {"meta": {"code": 400, "error": {"message": "Length of parameter 'page_size' should be from 1 to 10", "type": "paramIsOutsideSet"}}}
        answer = {"meta": {"code": 200}, "result": {"items": [{"id": "1", "name": "Завод"}], "total": 1}}
        sizes = []

        def fake_get(url, **kwargs):
            sizes.append(kwargs["params"]["page_size"])
            return FakeResponse(payload=limited if kwargs["params"]["page_size"] > 10 else answer)

        city = {"name": "Астана", "lat": 51.1, "lng": 71.4}
        with mock.patch.object(maps, "_dgis_page_size", maps.DGIS_PAGE_SIZE), mock.patch.object(config, "DGIS_API_KEY", "k"), \
             mock.patch("requests.get", side_effect=fake_get):
            list(maps._dgis_pages("завод", city))
            list(maps._dgis_pages("стройка", city))
        self.assertEqual(sizes, [50, 10, 10])

    def test_2gis_key_error_is_shown_as_is(self):
        denied = {"meta": {"code": 403, "error": {"message": "Authorization error, incorrect key.", "type": "forbidden"}}}
        with mock.patch.object(config, "DGIS_API_KEY", "k"), mock.patch("requests.get", return_value=FakeResponse(payload=denied)):
            with self.assertRaisesRegex(maps.MapError, "incorrect key"):
                list(maps._dgis_pages("завод", {"name": "Астана", "lat": 51.1, "lng": 71.4}))

    def test_head_office_is_preferred_over_sales_point(self):
        branches = [{"name": "Группа, отдел продаж"}, {"name": "Группа"}, {"name": "Группа, головной офис"}]
        self.assertEqual(sorted(branches, key=prospects._branch_rank)[0]["name"], "Группа, головной офис")
        self.assertEqual(sorted(branches, key=prospects._branch_rank)[-1]["name"], "Группа, отдел продаж")

    def test_2gis_without_contact_permission_has_no_phones_but_works(self):
        biz = maps._from_dgis({"id": "5", "name": "Завод"})
        self.assertEqual(biz["phones"], [])
        self.assertEqual(biz["name"], "Завод")

    def test_google_falls_back_to_legacy_on_403(self):
        legacy = {"status": "OK", "results": [{"place_id": "x1", "name": "ТОО Старый ключ", "types": ["store", "establishment"]}]}
        with mock.patch.object(config, "GOOGLE_PLACES_API_KEY", "k"), \
             mock.patch("requests.post", return_value=FakeResponse(status=403, payload={"error": {"message": "disabled"}})), \
             mock.patch("requests.get", return_value=FakeResponse(payload=legacy)):
            pages = list(maps._google_pages("завод", {"name": "Астана", "lat": 51.1, "lng": 71.4}))
        self.assertEqual(pages[0][0]["name"], "ТОО Старый ключ")
        self.assertTrue(pages[0][0]["needs_details"])
        self.assertEqual(pages[0][0]["rubrics"], ["store"])

    def test_disabled_api_gives_a_link_to_enable_it(self):
        new_api = {"error": {"message": "Places API (New) has not been used in project 1 before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/places.googleapis.com/overview?project=1 then retry."}}
        legacy = {"status": "REQUEST_DENIED", "error_message": "You're calling a legacy API"}
        with mock.patch.object(config, "GOOGLE_PLACES_API_KEY", "k"), \
             mock.patch("requests.post", return_value=FakeResponse(status=403, payload=new_api)), \
             mock.patch("requests.get", return_value=FakeResponse(payload=legacy)):
            with self.assertRaises(maps.MapError) as caught:
                list(maps._google_pages("завод", {"name": "Астана", "lat": 51.1, "lng": 71.4}))
        self.assertIn("не включён Places API (New)", str(caught.exception))
        self.assertIn("https://console.developers.google.com/apis/api/places.googleapis.com/overview?project=1", str(caught.exception))

    def test_missing_billing_is_named_as_the_reason(self):
        new_api = {"error": {"message": "The caller does not have permission"}}
        legacy = {"status": "REQUEST_DENIED", "error_message": "You must enable Billing on the Google Cloud Project"}
        with mock.patch.object(config, "GOOGLE_PLACES_API_KEY", "k"), \
             mock.patch("requests.post", return_value=FakeResponse(status=403, payload=new_api)), \
             mock.patch("requests.get", return_value=FakeResponse(payload=legacy)):
            with self.assertRaisesRegex(maps.MapError, "не подключён биллинг"):
                list(maps._google_pages("завод", {"name": "Астана", "lat": 51.1, "lng": 71.4}))

    def test_other_403_keeps_googles_own_reason(self):
        new_api = {"error": {"message": "Requests from this IP are blocked."}}
        legacy = {"status": "REQUEST_DENIED", "error_message": "denied"}
        with mock.patch.object(config, "GOOGLE_PLACES_API_KEY", "k"), \
             mock.patch("requests.post", return_value=FakeResponse(status=403, payload=new_api)), \
             mock.patch("requests.get", return_value=FakeResponse(payload=legacy)):
            with self.assertRaisesRegex(maps.MapError, "Requests from this IP are blocked"):
                list(maps._google_pages("завод", {"name": "Астана", "lat": 51.1, "lng": 71.4}))

    def test_far_away_results_are_dropped(self):
        city = {"name": "Астана", "lat": 51.17, "lng": 71.45}
        self.assertTrue(maps.within_city({"lat": 51.2, "lng": 71.5}, city))
        self.assertFalse(maps.within_city({"lat": 43.2, "lng": 76.9}, city))
        self.assertTrue(maps.within_city({"lat": None, "lng": None}, city))


class Normalization(unittest.TestCase):
    def test_name_key_ignores_legal_form_quotes_and_case(self):
        self.assertEqual(db.name_key("ТОО «Альфа-Строй»"), db.name_key('альфа строй ТОО'))
        self.assertEqual(db.name_key("ИП Иванов"), db.name_key("Иванов"))

    def test_phone_key_treats_8_and_plus7_as_same(self):
        self.assertEqual(db.phone_key("8 (701) 555-44-33"), db.phone_key("+7 701 555 44 33"))
        self.assertEqual(db.phone_key("123"), "")

    def test_search_phrases_that_would_find_sellers_are_dropped(self):
        data = {
            "offer_nom": "металлопрокат",
            "examples": ["лист", "труба", "балка", "швеллер", "арматура"],
            "products": ["лист", "труба"],
            "search_phrases": [
                "поставщик металлопроката", "купить лист металл", "трубы стальные оптом",
                "балки для строительства", "арматура для бетонных работ",
                "строительная компания", "завод ЖБИ",
            ],
        }
        self.assertEqual(prospects.buyer_phrases(data), ["строительная компания", "завод ЖБИ"])

    def test_same_search_in_other_word_forms_is_requested_once(self):
        profile = {"data": {"offer_nom": "упаковка", "examples": [], "products": [],
                            "search_phrases": ["строительные компании", "мебельный цех"], "activity_keys": ["construction"]}}
        params = {"activity_text": "", "activities": []}
        self.assertEqual(
            prospects._search_phrases(params, profile),
            [("строительные компании", "construction"), ("мебельный цех", None)],
        )

    def test_size_guess_from_name_and_branches(self):
        self.assertEqual(prospects.guess_size("ИП Иванов", None)[0], "ip")
        self.assertEqual(prospects.guess_size("АО Завод", None)[0], "large")
        self.assertEqual(prospects.guess_size("ТОО Завод", None)[0], "small")
        self.assertEqual(prospects.guess_size("Завод", 30)[0], "large")
        self.assertEqual(prospects.guess_size("Завод", 7)[0], "medium")
        self.assertEqual(prospects.guess_size("Завод", None)[0], "unknown")
        # Слова, внутри которых есть «ип» или «ао», не считаются формой
        self.assertEqual(prospects.guess_size("Типография", None)[0], "unknown")


class CompanyInput(DatabaseCase):
    def test_url_detection(self):
        for value in ("https://site.kz", "site.kz", "www.site.kz/about"):
            self.assertTrue(company.looks_like_url(value), value)
        for value in ("Продаём упаковку", "упаковка, плёнка", ""):
            self.assertFalse(company.looks_like_url(value), value)

    def test_internal_addresses_are_refused(self):
        for url in ("http://127.0.0.1:5050/", "http://localhost/", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd"):
            with self.assertRaises(company.CompanyInputError):
                company.fetch_page(url)

    def test_html_text_drops_scripts_and_keeps_title(self):
        page = '<html><title>Упак</title><meta name="description" content="Картон"><script>var a=1</script><p>Плёнка &amp; лента</p></html>'
        text = company.html_to_text(page)
        self.assertIn("Упак", text)
        self.assertIn("Картон", text)
        self.assertIn("Плёнка & лента", text)
        self.assertNotIn("var a", text)

    def test_model_output_is_validated(self):
        profile = company.clean_profile(PROFILE_ANSWER, "", "упаковка")
        self.assertEqual(profile["activity_keys"], ["production", "construction"])
        self.assertEqual(profile["offer_gen"], "упаковки")

    def test_missing_grammar_forms_fall_back_to_safe_wording(self):
        profile = company.clean_profile({"offer_nom": "картон"}, "", "картон")
        self.assertEqual(profile["offer_gen"], "направления «картон»")

    def test_repeated_analysis_uses_saved_profile(self):
        answer = FakeResponse(payload={"choices": [{"message": {"content": json.dumps(PROFILE_ANSWER, ensure_ascii=False)}, "finish_reason": "stop"}]})
        with mock.patch("requests.post", return_value=answer) as post:
            first, _ = company.analyze_company("Продаём упаковку", "упаковка")
            second, _ = company.analyze_company("Продаём упаковку", "упаковка")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(post.call_count, 1)


class ModelClient(DatabaseCase):
    def test_parses_fenced_json(self):
        self.assertEqual(llm.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm.parse_json('Вот ответ: {"a": 1} готово'), {"a": 1})
        with self.assertRaises(ValueError):
            llm.parse_json("нет данных")

    def test_retries_after_short_rate_limit(self):
        ok = FakeResponse(payload={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]})
        limited = FakeResponse(status=429, payload={}, headers={"retry-after": "1"})
        with mock.patch("requests.post", side_effect=[limited, ok]), mock.patch("time.sleep") as sleep:
            self.assertEqual(llm.chat_json("s", "u"), {"a": 1})
        sleep.assert_called_once_with(1.0)

    def test_long_rate_limit_is_not_waited_for(self):
        limited = FakeResponse(status=429, payload={}, headers={"retry-after": "3600"})
        with mock.patch("requests.post", return_value=limited), mock.patch("time.sleep") as sleep:
            with self.assertRaises(llm.LLMError) as caught:
                llm.chat_json("s", "u")
        self.assertEqual(caught.exception.code, "rate_limited")
        sleep.assert_not_called()

    def test_invalid_key_is_reported_without_retry(self):
        with mock.patch("requests.post", return_value=FakeResponse(status=401, payload={})) as post:
            with self.assertRaises(llm.LLMError) as caught:
                llm.chat_json("s", "u")
        self.assertEqual(caught.exception.code, "bad_key")
        self.assertEqual(post.call_count, 1)

    def test_truncated_answer_is_not_accepted(self):
        cut = FakeResponse(payload={"choices": [{"message": {"content": '{"a": 1'}, "finish_reason": "length"}]})
        with mock.patch("requests.post", return_value=cut):
            with self.assertRaises(llm.LLMError):
                llm.chat_json("s", "u")

    def test_key_is_not_leaked_in_errors(self):
        with mock.patch("requests.post", return_value=FakeResponse(status=500, payload={})):
            with self.assertRaises(llm.LLMError) as caught:
                llm.chat_json("s", "u")
        self.assertNotIn("llm-test", caught.exception.message)


if __name__ == "__main__":
    unittest.main()

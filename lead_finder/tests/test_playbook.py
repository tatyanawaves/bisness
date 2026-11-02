"""Скрипт должен идти по урокам для любой сферы, а не только для одного товара."""

import re
import unittest

from lead_finder import playbook
from lead_finder.activities import ACTIVITIES
from lead_finder.company import fallback_profile

BUSINESS = {"name": "ТОО Пример", "city": "Астана", "address": "ул. Примерная, 1", "phones": ["+77010000000"]}

CLEANING = {
    "name": "Чистый офис",
    "summary": "Уборка офисов и складов",
    "is_service": True,
    "offer_nom": "услуги клининга",
    "offer_gen": "услуг клининга",
    "offer_dat": "услугам клининга",
    "examples": ["уборка офисов", "мойка окон"],
    "products": ["уборка офисов"],
    "activity_keys": ["offices"],
    "search_phrases": [],
}
PACKAGING = {
    "name": "Упак-Трейд",
    "summary": "Гофрокартон и плёнка для производств",
    "is_service": False,
    "offer_nom": "упаковка",
    "offer_gen": "упаковки",
    "offer_dat": "упаковке",
    "examples": ["гофрокартон", "стрейч-плёнка"],
    "products": ["гофрокартон"],
    "activity_keys": ["production"],
    "search_phrases": [],
}


def compose(offer, activity_key=None, ideas=None, size=None):
    analysis = {"data": {"activity_key": activity_key, "size": size}}
    slots = playbook.default_slots(analysis, offer)
    slots["ideas"] = ideas or []
    return playbook.compose(BUSINESS, analysis, offer, slots, "Алия")


class ScriptFollowsLessons(unittest.TestCase):
    def test_stages_go_in_the_requested_order(self):
        content = compose(PACKAGING, "production")
        self.assertEqual(
            [stage["id"] for stage in content["stages"]],
            ["gatekeeper", "opening", "regular", "requests", "supplier", "offer", "decision", "next_step"],
        )

    def test_after_buyer_asks_regular_positions_requests_and_supplier(self):
        text = playbook.to_plain_text(compose(PACKAGING, "production"))
        self.assertIn("Что из упаковки у вас чаще всего закупается?", text)
        self.assertIn("есть актуальные заявки", text)
        self.assertIn("всё нормально или периодически возникают вопросы по цене или срокам", text)
        self.assertIn("Дополнительного поставщика рассматриваете", text)
        self.assertIn("вы сравните нас с текущими поставщиками", text)

    def test_hypothesis_from_analysis_is_offered_as_a_question(self):
        idea = {"product": "гофрокартон", "why": "Швейному цеху нужна упаковка", "question": "Компании вашего профиля обычно закупают гофрокартон. У вас это проходит через закупку?"}
        content = compose(PACKAGING, "production", ideas=[idea])
        offer_stage = next(stage for stage in content["stages"] if stage["id"] == "offer")
        line = next(line for line in offer_stage["lines"] if "гофрокартон" in line.get("if", ""))
        self.assertTrue(line["says"][0].endswith("?"))
        self.assertIn("предположение", line["note"])

    def test_objections_from_lessons_are_all_present(self):
        triggers = {objection["trigger"] for objection in compose(PACKAGING)["objections"]}
        for trigger in ("Скиньте КП", "Ничего не нужно", "Дорого", "Подумаем", "Перезвоните позже", "Сами позвоним"):
            self.assertIn(trigger, triggers)

    def test_no_forbidden_phrases_for_any_activity_or_offer(self):
        for offer in (PACKAGING, CLEANING, fallback_profile("", "канцтовары, бумага")):
            for activity in ACTIVITIES:
                self.assertEqual(playbook.lint(compose(offer, activity["key"])), [], (offer["offer_nom"], activity["key"]))

    def test_lines_do_not_assume_the_speakers_gender(self):
        gendered = re.compile(r"\b(хотел|понял|звонил|попал|сам свяжусь|уточнил)\b", re.IGNORECASE)
        for line in playbook.spoken_lines(compose(CLEANING, "offices")):
            self.assertIsNone(gendered.search(line), line)


class ScriptIsUniversal(unittest.TestCase):
    METAL_WORDS = re.compile(r"металл|прокат|арматур|швеллер|двутавр|\bлист|\bтруб", re.IGNORECASE)

    def test_no_metal_vocabulary_for_other_businesses(self):
        for offer in (CLEANING, PACKAGING):
            for activity in ACTIVITIES:
                if activity["key"] == "metalwork":
                    continue
                text = playbook.to_plain_text(compose(offer, activity["key"]))
                self.assertIsNone(self.METAL_WORDS.search(text), (offer["offer_nom"], activity["key"]))

    def test_services_use_contractor_wording(self):
        text = playbook.to_plain_text(compose(CLEANING, "offices"))
        self.assertIn("подрядчик", text)
        self.assertNotIn("поставщик", text)
        self.assertIn("услуг клининга", text)
        self.assertIn("Что из услуг клининга у вас чаще всего заказывается?", text)
        self.assertNotIn("докупать", text)

    def test_without_model_wording_stays_grammatical(self):
        offer = fallback_profile("", "канцтовары")
        text = playbook.to_plain_text(compose(offer, "offices"))
        self.assertIn("направления «канцтовары»", text)
        self.assertNotIn("{", text)

    def test_small_business_note_mentions_owner(self):
        content = compose(PACKAGING, "retail", size="small")
        self.assertIn("владелец", content["stages"][0]["lines"][0]["note"])


class SlotValidation(unittest.TestCase):
    def setUp(self):
        self.defaults = playbook.default_slots({"data": {"activity_key": "production"}}, PACKAGING)

    def test_forbidden_model_text_is_replaced_by_default(self):
        slots, rejected = playbook.clean_slots(
            {"process_question": "Хотели бы предложить вам сотрудничество?", "volume_question": "Сколько коробок в месяц?"},
            self.defaults,
        )
        self.assertEqual(slots["process_question"], self.defaults["process_question"])
        self.assertEqual(slots["volume_question"], "Сколько коробок в месяц?")
        self.assertIn("process_question", rejected)

    def test_model_wording_is_normalized_for_the_script(self):
        slots, _ = playbook.clean_slots(
            {
                "secretary_question": "Подскажите, кто в компании отвечает за закупку упаковки?",
                "volume_question": "какие объёмы закупаете за один раз?",
            },
            self.defaults,
        )
        self.assertEqual(slots["secretary_question"], "кто в компании отвечает за закупку упаковки?")
        self.assertEqual(slots["volume_question"], "Какие объёмы закупаете за один раз?")

    def test_each_sentence_of_a_model_question_starts_with_a_capital(self):
        slots, _ = playbook.clean_slots(
            {"ideas": [{"product": "балка", "why": "x", "question": "компании вашего профиля закупают балки. у вас это проходит через закупку?"}]},
            self.defaults,
        )
        self.assertEqual(slots["ideas"][0]["question"], "Компании вашего профиля закупают балки. У вас это проходит через закупку?")

    def test_abbreviation_at_start_keeps_its_case(self):
        slots, _ = playbook.clean_slots({"secretary_question": "ОМТС или снабжение отвечает за упаковку?"}, self.defaults)
        self.assertEqual(slots["secretary_question"], "ОМТС или снабжение отвечает за упаковку?")

    def test_not_a_question_is_rejected(self):
        slots, _ = playbook.clean_slots({"volume_question": "Объём обычно большой."}, self.defaults)
        self.assertEqual(slots["volume_question"], self.defaults["volume_question"])

    def test_needs_questions_are_forbidden_in_any_word_order(self):
        for phrase in (
            "Вам нужны регулярные поставки стальных труб для объектов?",
            "Вам случайно картон не нужен?",
            "Нужна ли вам упаковка?",
            "Вам требуется упаковка?",
        ):
            self.assertTrue(playbook.find_forbidden(phrase), phrase)
        self.assertEqual(playbook.find_forbidden("Что из упаковки у вас чаще всего закупается?"), [])

    def test_bad_ideas_are_dropped(self):
        slots, _ = playbook.clean_slots(
            {"ideas": [{"product": "плёнка", "why": "x", "question": "У вас есть потребность в плёнке?"},
                       {"product": "картон", "why": "x", "question": "Картон у вас проходит через закупку?"},
                       "мусор"]},
            self.defaults,
        )
        self.assertEqual([idea["product"] for idea in slots["ideas"]], ["картон"])


if __name__ == "__main__":
    unittest.main()

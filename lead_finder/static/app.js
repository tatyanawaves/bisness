"use strict";

/* Весь текст из внешних источников попадает на страницу только через textContent */
function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
        if (child !== null && child !== undefined && child !== false) node.append(child);
    }
    return node;
}

const $ = (id) => document.getElementById(id);

const state = {
    profileId: null,
    openBusinessId: null,
    openScript: null,
    results: [],
    sizeLabels: { unknown: "Размер неизвестен" },
};

const MONTHLY_LABELS = {
    high: "Закупает регулярно",
    medium: "Закупает время от времени",
    low: "Закупает редко",
};

async function api(path, options = {}) {
    const response = await fetch(path, {
        ...options,
        headers: { "Content-Type": "application/json" },
        body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
    return data;
}

function remember(key, value) {
    try { localStorage.setItem(key, value); } catch { /* Хранилище браузера необязательно */ }
}

function recall(key) {
    try { return localStorage.getItem(key) || ""; } catch { return ""; }
}

function formatDate(iso) {
    return new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function capitalize(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function clear(node) {
    node.replaceChildren();
}

/* ---------- Форма поиска ---------- */

function chip(name, value, label) {
    return el("label", { class: "chip" },
        el("input", { type: "checkbox", name, value }),
        el("span", { text: label }));
}

function checkedValues(name) {
    return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

async function loadMeta() {
    const meta = await api("/api/meta");
    const city = $("city");
    for (const name of meta.cities) city.append(el("option", { value: name, text: name }));
    city.value = recall("city") || meta.cities[0];

    for (const activity of meta.activities) $("activities").append(chip("activity", activity.key, activity.label));
    for (const size of meta.sizes) {
        $("sizes").append(chip("size", size.key, size.label));
        state.sizeLabels[size.key] = size.label;
    }
    $("count").max = meta.max_count;
    $("manager").value = recall("manager");
    $("offer").value = recall("offer");
    $("company").value = recall("company");

    $("keys").textContent = `Карты: ${meta.maps.label}. Модель: ${meta.llm.configured ? meta.llm.model : "не подключена"}`;

    const missing = [];
    if (!meta.maps.provider) missing.push("ключ карт (GOOGLE_PLACES_API_KEY или DGIS_API_KEY), без него поиск не запустится");
    if (!meta.llm.configured) missing.push("GROQ_API_KEY, без него анализ и скрипты собираются без ИИ");
    if (missing.length) {
        const notice = $("setup-notice");
        notice.hidden = false;
        notice.append("Добавьте в файл lead_finder/.env и перезапустите приложение: ");
        notice.append(missing.join("; ") + ".");
    }
}

function renderProfile(profile) {
    const card = $("profile-card");
    clear(card);
    if (!profile) { card.hidden = true; return; }
    state.profileId = profile.id;
    card.hidden = false;
    card.append(el("h3", { text: profile.name ? `Как мы поняли ${profile.name}` : "Как мы поняли ваше предложение" }));
    card.append(el("p", { text: profile.summary || profile.offer_nom }));
    if (profile.examples?.length) card.append(el("p", { text: `Главное: ${profile.examples.join(", ")}` }));
    if (!profile.is_ai) card.append(el("p", { text: "Разобрано без ИИ, только по вашему тексту." }));
}

/* ---------- Поиск ---------- */

function setFormError(text) {
    const box = $("form-error");
    clear(box);
    // Ссылку из сообщения делаем кликабельной, например на включение API в консоли Google
    const [before, url] = (text || "").split(/(https:\/\/\S+)/);
    box.append(before || "");
    if (url) box.append(el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: url }));
    box.hidden = !text;
    if (text) box.scrollIntoView({ block: "nearest" });
}

function addWarning(text) {
    $("warnings").append(el("p", { text }));
}

function factList(analysis) {
    if (!analysis) return [];
    const facts = [
        el("span", { class: "fact", title: analysis.size_why || "", text: state.sizeLabels[analysis.size] || analysis.size }),
    ];
    if (analysis.monthly) {
        facts.push(el("span", {
            class: `fact${analysis.monthly === "low" ? " is-low" : ""}`,
            title: analysis.monthly_why || "",
            text: MONTHLY_LABELS[analysis.monthly] || analysis.monthly,
        }));
    }
    if (analysis.is_ai) facts.push(el("span", { class: "fact", title: "Насколько компании подходит ваше предложение, по оценке модели", text: `Подходит на ${analysis.fit}%` }));
    return facts;
}

function phoneLink(phone) {
    return el("a", { class: "phone", href: `tel:${phone.replace(/[^\d+]/g, "")}`, text: phone });
}

// Где посмотреть телефон: карточка компании в 2ГИС, а если её нет, поиск по названию
function phoneLookupUrl(business) {
    if (business.map_url?.includes("2gis.")) return business.map_url;
    return `https://2gis.kz/search/${encodeURIComponent(`${business.name} ${business.city}`)}`;
}

function renderCompany(business) {
    const analysis = business.analysis;
    const meta = [];
    if (business.phones?.length) {
        business.phones.slice(0, 2).forEach((phone, index) => {
            if (index) meta.push(", ");
            meta.push(phoneLink(phone));
        });
    } else {
        meta.push(el("span", { class: "no-phone", text: "Телефона нет в данных. " }));
        meta.push(el("a", { href: phoneLookupUrl(business), target: "_blank", rel: "noopener noreferrer", text: "Посмотреть в 2ГИС" }));
    }
    if (business.address) meta.push(` ${business.address}`);

    const links = [];
    if (business.website) links.push(el("a", { href: business.website, target: "_blank", rel: "noopener noreferrer", text: "Сайт" }));
    if (business.map_url && business.phones?.length) links.push(el("a", { href: business.map_url, target: "_blank", rel: "noopener noreferrer", text: "Карта" }));

    const callButton = el("button", { type: "button", class: "call", text: "Звонок", onclick: () => openScript(business, callButton) });
    const workedButton = el("button", {
        type: "button",
        class: "quiet",
        text: "Отработан",
        title: "Компания больше не появится в поиске этого города",
        onclick: () => markWorked(business, workedButton),
    });

    const row = el("li", { class: "company", "data-id": business.id },
        el("div", {},
            el("h3", { class: "company-name", text: business.name }),
            analysis?.activity ? el("p", { class: "company-meta", text: analysis.activity }) : null,
            el("p", { class: "company-meta" }, meta),
            links.length ? el("p", { class: "company-meta" }, links.flatMap((link, i) => (i ? [" ", link] : [link]))) : null,
            el("div", { class: "facts" }, factList(analysis)),
            analysis?.idea ? el("p", { class: "idea", text: `Можно предложить: ${analysis.idea.product}. ${capitalize(analysis.idea.why)}` }) :
                analysis?.buys?.length ? el("p", { class: "idea", text: `Вероятно закупает: ${analysis.buys.join(", ")}` }) : null),
        el("div", { class: "company-actions" }, callButton, workedButton));
    return row;
}

function renderSummary(done) {
    const summary = $("summary");
    clear(summary);
    summary.append(el("h2", { text: `${done.city}: найдено ${done.found} из ${done.requested}` }));
    const parts = Object.entries(done.by_size).map(([label, value]) => `${label}: ${value}`);
    const detail = [];
    if (parts.length) detail.push(parts.join(", "));
    if (done.skipped_worked) detail.push(`пропущено отработанных: ${done.skipped_worked}`);
    const filtered = done.dropped.size + done.dropped.not_regular + done.dropped.not_fit;
    if (filtered) detail.push(`отсеяно фильтрами и анализом: ${filtered}`);
    if (detail.length) summary.append(el("p", { text: detail.join("; ") }));
    if (done.found) summary.append(el("p", { text: "Размер и регулярность закупок это оценка по открытым данным, а не отчётность компании. Причина оценки видна при наведении." }));
    if (done.found < done.requested) {
        summary.append(el("p", { text: done.found === 0
            ? "Ничего не подошло. Снимите часть фильтров или выберите другую деятельность."
            : "Больше подходящих компаний не нашлось. Попробуйте другую деятельность или снимите фильтр размера." }));
    }
}

function sortResults() {
    const list = $("company-list");
    const fit = (business) => business.analysis?.fit ?? 0;
    const hasPhone = (business) => (business.phones?.length ? 1 : 0);
    state.results.sort((a, b) => hasPhone(b) - hasPhone(a) || fit(b) - fit(a));
    clear(list);
    for (const business of state.results) list.append(renderCompany(business));
}

async function runSearch(event) {
    event.preventDefault();
    setFormError("");
    const offer = $("offer").value.trim();
    const company = $("company").value.trim();
    const count = Number($("count").value);
    if (!offer && !company) {
        setFormError("Напишите, что хотите продать, или опишите компанию.");
        $("offer").focus();
        return;
    }
    if (!Number.isInteger(count) || count < 1 || count > Number($("count").max)) {
        setFormError(`Укажите количество от 1 до ${$("count").max}.`);
        $("count").focus();
        return;
    }

    remember("city", $("city").value);
    remember("manager", $("manager").value.trim());
    remember("offer", offer);
    remember("company", company);

    const button = $("search-button");
    button.disabled = true;
    button.textContent = "Ищем…";
    $("empty").hidden = true;
    clear($("warnings"));
    clear($("summary"));
    clear($("company-list"));
    state.results = [];
    closeScript();
    const progress = $("progress");
    progress.hidden = false;
    progress.textContent = "Начинаем поиск";
    revealResults();

    try {
        const response = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                city: $("city").value,
                count,
                offer,
                company,
                activities: checkedValues("activity"),
                activity_text: $("activity-text").value.trim(),
                sizes: checkedValues("size"),
                only_regular: $("only-regular").checked,
            }),
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || `Ошибка ${response.status}`);
        }
        await readEvents(response, handleEvent);
    } catch (error) {
        setFormError(error.message || "Не удалось выполнить поиск. Проверьте, что приложение запущено.");
        $("empty").hidden = state.results.length > 0;
    } finally {
        progress.hidden = true;
        button.disabled = false;
        button.textContent = "Найти компании";
    }
}

// На телефоне форма длинная, результаты оказываются под ней
function revealResults() {
    if (window.matchMedia("(max-width: 760px)").matches) document.querySelector(".results").scrollIntoView();
}

async function readEvents(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function handleEvent(event) {
    switch (event.type) {
        case "status":
            $("progress").textContent = event.text;
            break;
        case "warning":
            addWarning(event.text);
            break;
        case "profile":
            renderProfile(event.profile);
            revealResults();
            break;
        case "business":
            state.results.push(event.business);
            $("company-list").append(renderCompany(event.business));
            break;
        case "done":
            renderSummary(event);
            sortResults();
            break;
        case "error":
            throw new Error(event.text);
    }
}

async function markWorked(business, button) {
    button.disabled = true;
    try {
        await api(`/api/businesses/${business.id}/worked`, { method: "POST", body: { worked: true } });
        state.results = state.results.filter((item) => item.id !== business.id);
        document.querySelector(`.company[data-id="${business.id}"]`)?.remove();
        if (state.openBusinessId === business.id) closeScript();
        const summary = $("summary").querySelector("h2");
        if (summary) summary.after(el("p", { text: `${business.name} отмечена отработанной и больше не появится в поиске. Вернуть можно в разделе «Отработанные».` }));
    } catch (error) {
        button.disabled = false;
        setFormError(error.message);
    }
}

/* ---------- Скрипт звонка ---------- */

async function openScript(business, button) {
    if (!state.profileId) {
        setFormError("Сначала запустите поиск: скрипт строится на разборе вашей компании.");
        return;
    }
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Готовим…";
    try {
        const { script } = await api(`/api/businesses/${business.id}/script`, {
            method: "POST",
            body: { profile_id: state.profileId, manager_name: $("manager").value.trim() },
        });
        showScript(script, business);
    } catch (error) {
        setFormError(error.message);
    } finally {
        button.disabled = false;
        button.textContent = original;
    }
}

function closeScript() {
    $("script-panel").hidden = true;
    document.querySelector(".company.is-open")?.classList.remove("is-open");
    state.openBusinessId = null;
    state.openScript = null;
}

function renderSay(text) {
    return el("p", { class: "say", text });
}

function renderLine(line) {
    if ("say" in line) {
        return el("div", { class: "line" }, renderSay(line.say), line.note ? el("p", { class: "note", text: line.note }) : null);
    }
    return el("div", { class: "reply" },
        el("p", { class: "reply-if", text: line.if }),
        line.says.map(renderSay),
        line.note ? el("p", { class: "note", text: line.note }) : null);
}

function renderBrief(content) {
    const analysis = content.analysis || {};
    const parts = [];
    if (analysis.activity) parts.push(el("p", { text: analysis.activity }));
    const facts = [];
    if (analysis.size) facts.push(`${state.sizeLabels[analysis.size] || analysis.size}${analysis.size_why ? ` (${analysis.size_why})` : ""}`);
    if (analysis.monthly) facts.push(`${MONTHLY_LABELS[analysis.monthly]}${analysis.monthly_why ? ` (${analysis.monthly_why})` : ""}`);
    if (facts.length) parts.push(el("p", { class: "muted", text: `Оценка: ${facts.join("; ")}.` }));
    if (analysis.buys?.length) parts.push(el("p", { text: `Вероятно закупает: ${analysis.buys.join(", ")}.` }));
    parts.push(el("p", { text: `Цель звонка: не продать, а найти вход в закупки. Обычно за закупку отвечает: ${content.buyer_role}.` }));
    return el("div", { class: "brief" }, el("h3", { text: "Перед звонком" }), parts);
}

function showScript(script, business) {
    const content = script.content;
    state.openScript = script;
    state.openBusinessId = script.business_id;
    document.querySelector(".company.is-open")?.classList.remove("is-open");
    document.querySelector(`.company[data-id="${script.business_id}"]`)?.classList.add("is-open");

    // Шапка
    const head = $("script-head");
    clear(head);
    const company = content.company;
    const contactLine = [];
    company.phones?.slice(0, 2).forEach((phone) => contactLine.push(phoneLink(phone), " "));
    if (!company.phones?.length) {
        contactLine.push(el("a", { href: phoneLookupUrl(company), target: "_blank", rel: "noopener noreferrer", text: "Посмотреть телефон в 2ГИС" }));
    }
    const isWorked = script.business_status === "worked";
    const actions = [];
    if (business && state.profileId) {
        const again = el("button", { type: "button", class: "quiet", text: "Сгенерировать заново", onclick: () => openScript(business, again) });
        actions.push(again);
    }
    const copy = el("button", { type: "button", class: "quiet", text: "Скопировать", onclick: async () => {
        try {
            await navigator.clipboard.writeText(script.plain_text);
            copy.textContent = "Скопировано";
        } catch {
            copy.textContent = "Не удалось скопировать";
        }
        setTimeout(() => { copy.textContent = "Скопировать"; }, 1800);
    } });
    actions.push(copy);
    if (business && !isWorked) {
        const worked = el("button", { type: "button", class: "quiet", text: "Отработан", onclick: () => markWorked(business, worked) });
        actions.push(worked);
    }
    actions.push(el("button", { type: "button", class: "quiet", text: "Закрыть", onclick: closeScript }));

    head.append(
        el("div", {},
            el("h2", { text: company.name }),
            el("p", { class: "sub" }, contactLine, company.address ? ` ${company.address}` : "")),
        el("div", { class: "head-actions" }, actions));

    // Шаги и текст
    const ladder = $("ladder");
    const text = $("script-text");
    clear(ladder);
    clear(text);
    for (const warning of content.warnings || []) text.append(el("p", { class: "warning-line", text: warning }));
    text.append(renderBrief(content));

    content.stages.forEach((stage, index) => {
        const id = `stage-${stage.id}`;
        ladder.append(el("a", { href: `#${id}`, "data-stage": id },
            el("b", { text: String(index + 1) }), el("span", { text: stage.title })));
        text.append(el("section", { class: "stage", id },
            el("h3", { class: "stage-title", text: `${index + 1}. ${stage.title}` }),
            el("p", { class: "stage-goal", text: stage.goal }),
            stage.formula ? el("p", { class: "stage-formula", text: stage.formula }) : null,
            stage.lines.map(renderLine)));
    });

    text.append(el("div", { class: "extras" },
        el("h3", { text: "Сообщение в WhatsApp после звонка" }),
        el("p", { class: "say", text: content.whatsapp }),
        el("h3", { text: "После звонка запишите" }),
        el("ul", {}, content.after_call.map((item) => el("li", { text: item }))),
        el("h3", { text: "Не говорить" }),
        el("ul", { class: "never" }, content.never_say.map((item) => el("li", { text: item })))));

    // Возражения
    const buttons = $("objection-buttons");
    const answer = $("objection-answer");
    clear(buttons);
    clear(answer);
    answer.hidden = true;
    for (const objection of content.objections) {
        const button = el("button", { type: "button", "aria-pressed": "false", text: objection.trigger, onclick: () => {
            const isOpen = button.getAttribute("aria-pressed") === "true";
            buttons.querySelectorAll("button").forEach((other) => other.setAttribute("aria-pressed", "false"));
            clear(answer);
            answer.hidden = isOpen;
            if (isOpen) return;
            button.setAttribute("aria-pressed", "true");
            objection.says.forEach((say) => answer.append(renderSay(say)));
            if (objection.note) answer.append(el("p", { class: "note", text: objection.note }));
        } });
        buttons.append(button);
    }

    const panel = $("script-panel");
    panel.hidden = false;
    text.scrollTop = 0;
    panel.focus();
    watchStages(text, ladder);
}

let stageObserver = null;

function watchStages(text, ladder) {
    stageObserver?.disconnect();
    if (!("IntersectionObserver" in window)) return;
    stageObserver = new IntersectionObserver((entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting);
        if (!visible.length) return;
        const id = visible[0].target.id;
        ladder.querySelectorAll("a").forEach((link) => link.classList.toggle("is-current", link.dataset.stage === id));
    }, { root: text, rootMargin: "0px 0px -70% 0px" });
    text.querySelectorAll(".stage").forEach((stage) => stageObserver.observe(stage));
}

/* ---------- Разделы базы ---------- */

function showView(name) {
    document.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
    document.querySelectorAll(".tab").forEach((tab) => {
        if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
        else tab.removeAttribute("aria-current");
    });
    closeScript();
    if (name === "library") loadLibrary();
    if (name === "worked") loadWorked();
}

function emptyRow(text) {
    return el("li", { class: "empty-row", text });
}

async function loadLibrary() {
    const scriptList = $("script-list");
    const analysisList = $("analysis-list");
    clear(scriptList);
    clear(analysisList);
    try {
        const [{ scripts }, { analyses }] = await Promise.all([api("/api/scripts"), api("/api/analyses")]);
        if (!scripts.length) scriptList.append(emptyRow("Пока нет скриптов. Нажмите «Звонок» рядом с найденной компанией."));
        for (const script of scripts) {
            const button = el("button", { type: "button", class: "quiet", text: "Открыть", onclick: async () => {
                const data = await api(`/api/scripts/${script.id}`);
                showScript(data.script, null);
            } });
            scriptList.append(el("li", {},
                el("div", {},
                    el("h3", { text: script.business_name }),
                    el("p", { text: `${script.city}, ${formatDate(script.created_at)}${script.is_ai ? "" : ", без ИИ"}` })),
                button));
        }
        if (!analyses.length) analysisList.append(emptyRow("Анализы появятся после первого поиска."));
        for (const analysis of analyses) {
            const data = analysis.data;
            const details = [state.sizeLabels[data.size] || data.size, MONTHLY_LABELS[data.monthly]];
            if (data.activity) details.unshift(data.activity);
            if (analysis.is_ai) details.push(`подходит на ${data.fit}%`);
            analysisList.append(el("li", {},
                el("div", {},
                    el("h3", { text: analysis.business_name }),
                    el("p", { text: details.filter(Boolean).join(", ") }),
                    data.idea ? el("p", { text: `Можно предложить: ${data.idea.product}. ${capitalize(data.idea.why)}` }) : null,
                    el("p", { text: `${analysis.city}, ${formatDate(analysis.created_at)}${analysis.is_ai ? "" : ", без ИИ"}` }))));
        }
    } catch (error) {
        scriptList.append(emptyRow(error.message));
    }
}

async function loadWorked() {
    const list = $("worked-list");
    clear(list);
    try {
        const { businesses } = await api("/api/businesses/worked");
        if (!businesses.length) list.append(emptyRow("Пока никого не отмечали."));
        for (const business of businesses) {
            const button = el("button", { type: "button", class: "quiet", text: "Вернуть в поиск", onclick: async () => {
                button.disabled = true;
                await api(`/api/businesses/${business.id}/worked`, { method: "POST", body: { worked: false } });
                loadWorked();
            } });
            list.append(el("li", {},
                el("div", {},
                    el("h3", { text: business.name }),
                    el("p", { text: `${business.city}, отмечено ${formatDate(business.worked_at)}` })),
                button));
        }
    } catch (error) {
        list.append(emptyRow(error.message));
    }
}

/* ---------- Запуск ---------- */

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
$("search-form").addEventListener("submit", runSearch);
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("script-panel").hidden) closeScript();
});

// Если изменились данные о компании, разбор нужно сделать заново при следующем поиске
for (const id of ["offer", "company"]) {
    $(id).addEventListener("input", () => {
        state.profileId = null;
        renderProfile(null);
    });
}

loadMeta().catch((error) => setFormError(`Не удалось загрузить данные: ${error.message}`));

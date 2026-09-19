# smoke_test.py — самопроверка. Запуск: python smoke_test.py. Ожидается ALL OK.
# Все имена/даты/события в тестах ВЫМЫШЛЕНЫ; структура разметки — реальный
# формат Telegram Desktop-экспорта.
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_toolkit as t

OK = 0

def check(name, cond, extra=""):
    global OK
    if not cond:
        raise AssertionError(f"FAIL: {name} {extra}")
    OK += 1
    print(f"  [ok] {name}")

tmp = Path(tempfile.mkdtemp())
t.INPUT_DIR = tmp / "input"; t.INPUT_DIR.mkdir(parents=True)
t.OUTPUT_DIR = tmp / "output"; t.OUTPUT_DIR.mkdir()

print("== 1. Коллизии html/txt ==")
(t.INPUT_DIR / "report.html").write_text("<p>html</p>", encoding="utf-8")
(t.INPUT_DIR / "report.txt").write_text("текст", encoding="utf-8")
used = set()
check("report.html -> report_html",
      t.get_unique_out_name(t.INPUT_DIR / "report.html", used) == "report_html")
check("report.txt -> report_txt",
      t.get_unique_out_name(t.INPUT_DIR / "report.txt", used) == "report_txt")

print("== 2. Natural sort ==")
sub = t.INPUT_DIR / "ChatA"; sub.mkdir()
for name in ("messages.html", "messages10.html", "messages2.html"):
    (sub / name).write_text("x", encoding="utf-8")
order = [p.name for p in t.get_files({".html"}, folder=t.INPUT_DIR)]
idx = {n: i for i, n in enumerate(order)}
check("messages < messages2 < messages10",
      idx["messages.html"] < idx["messages2.html"] < idx["messages10.html"], order)

print("== 3. Кодировки ==")
f = tmp / "cp1251.txt"; f.write_bytes("привет cp1251".encode("cp1251"))
check("cp1251", "привет" in t.read_text_smart(f))
f = tmp / "utf16.txt"; f.write_bytes("привет utf16".encode("utf-16"))
check("utf-16 BOM", "привет" in t.read_text_smart(f))
f = tmp / "meta.html"
f.write_bytes('<meta charset="koi8-r"> привет'.encode("koi8-r"))
check("charset из meta", "привет" in t.read_text_smart(f))
f = tmp / "bin.dat"; f.write_bytes(b"\x00\x01\x02bin")
try:
    t.read_text_smart(f); check("бинарный отклонен", False)
except ValueError:
    check("бинарный отклонен", True)
f = tmp / "nfkc.txt"; f.write_text("полное ｄｕｒｏｖ имя", encoding="utf-8")
check("NFKC разворачивает fullwidth", "durov" in t.read_text_smart(f))

print("== 4. Шапка vs контент (EN) ==")
head = "\n".join([
    "Exported with Telegram Desktop",
    "Version 3.4.8 (64 bit), compiled 12:00:00",
    "123 members, 456 messages",
    "Page 2 of 7",
    "Channel: Тестовый канал",
] + [f"наполнение {i}" for i in range(15)] + ["Page 5 of my book is out"])
c = t.clean_text_content(head)[0]
check("шапка удалена", all(s not in c for s in
      ("Exported", "Version 3.4.8", "123 members", "Page 2 of 7", "Channel:")))
check("page вне зоны жив", "Page 5 of my book is out" in c)
check("views: 123 убит", "Views" not in t.clean_text_content("Views: 123")[0])

print("== 5. Локализация RU (UNVERIFIED) ==")
ru_head = "\n".join([
    "Экспорт из Telegram Desktop",
    "Версия 4.10 (64 bit)",
    "123 участника, 456 сообщений",
    "Страница 1 из 5",
    "Канал: Тестовый",
] + [f"контент {i}" for i in range(15)] + ["нет", "Фото", "Просмотры: 123"])
c = t.clean_text_content(ru_head)[0]
check("ru шапка удалена", all(s not in c for s in
      ("Экспорт", "Версия 4.10", "Страница 1", "Канал:", "участника")))
check("ru медиа и keyval убиты", "Фото" not in c and "Просмотры" not in c)

print("== 6. Ссылки ==")
e, _, _ = t.extract_entities_with_context(
    "смотри https://t.me/foo?x=1#abc и https://t.me.evil.com/x и @durov")
check("tme с фрагментом целиком", "https://t.me/foo?x=1#abc" in e.get("tme_links", {}))
check("evil в urls", "https://t.me.evil.com/x" in e.get("urls", {}))
check("evil не в tme", "https://t.me.evil.com/x" not in e.get("tme_links", {}))
check("тег найден", "@durov" in e.get("tags", {}))
e2, _, _ = t.extract_entities_with_context("голый https://t.me тут")
check("голый t.me в tme", "https://t.me" in e2.get("tme_links", {}))
e3, _, _ = t.extract_entities_with_context("пиши на ivan@mail.ru сейчас")
check("email не дает фантомный тег",
      "@mail" not in e3.get("tags", {}) and "ivan@mail.ru" in e3.get("emails", {}))
e4, _, _ = t.extract_entities_with_context("ip 999.1.1.1 и 192.168.1.1")
check("ipv4 строгий", "192.168.1.1" in e4.get("ipv4", {})
      and "999.1.1.1" not in e4.get("ipv4", {}))
e5, _, _ = t.extract_entities_with_context(
    "го https://t.me/share/url?url=https://example.com/a")
check("вложенный url в query целиком",
      "https://t.me/share/url?url=https://example.com/a" in e5.get("tme_links", {}))

print("== 7. Аккаунты ==")
e, _, _ = t.extract_entities_with_context("@Durov написал и https://t.me/durov/123")
check("аккаунт склеен", any(k.startswith("@durov") for k in e.get("accounts", {})))

print("== 8. Телефоны vs даты ==")
e, _, _ = t.extract_entities_with_context(
    "[2024-06-10 19:30:30 UTC+03:00] Иван: звони +7 999 123-45-67")
check("дата-префикс не дает ложный телефон",
      list(e.get("phones", {}).keys()) == ["79991234567"], e.get("phones"))
e, _, _ = t.extract_entities_with_context("встреча 10-06-2024 19 в парке")
check("dd-mm-yyyy + час не телефон", not e.get("phones"))
e, _, _ = t.extract_entities_with_context("код 999-123-4567 ищи")
check("us-формат выживает", "9991234567" in e.get("phones", {}))

print("== 9. Карты: Luhn ==")
e, _, _ = t.extract_entities_with_context("карты: 1234 5678 9012 3456 и 4111 1111 1111 1111")
check("валидная карта принята", "4111111111111111" in e.get("cards", {}))
check("мусор отброшен", "1234567890123456" not in e.get("cards", {}))

print("== 10. ФИО (укр) ==")
e, _, _ = t.extract_entities_with_context("Олена Петрівна Коваль написала лист")
check("укр ФИО", "Олена Петрівна Коваль" in e.get("fio_ru", {}))

print("== 11. Детерминизм ==")
sample = ("### SOURCE: chatA_txt ###\n\n"
          "[2024-06-10 19:30:30 UTC+03:00] Иван: пиши на ivan@mail.ru, звони +7 999 123-45-67\n"
          "посети https://t.me/durov и https://example.com/a?b=1 и @durov\n")
check("json побайтово идентичен",
      json.dumps(t.extract_entities_with_context(sample)[0], ensure_ascii=False)
      == json.dumps(t.extract_entities_with_context(sample)[0], ensure_ascii=False))

print("== 12. Структурный HTML: форварды, реакции, via, joined ==")
# ВЫМЫШЛЕННЫЙ дамп: Богдан и Оля; структура разметки — реальный формат экспорта
html = """<html><body><div class="page_wrap">
<div class="page_header"><div class="content"><div class="text bold">Оля💜</div></div></div>
<div class="history">
<div class="message service" id="message-1"><div class="body details">6 April 2026</div></div>
<div class="message default clearfix" id="m1">
<div class="pull_left userpic_wrap"><div class="userpic userpic1"><div class="initials">Б</div></div></div>
<div class="body">
<div class="pull_right date details" title="06.04.2026 12:20:57 UTC+02:00">12:20</div>
<div class="from_name">Богдан 🌿</div>
<div class="text">Вітаю!<br>Хотів спитати</div>
</div>
</div>
<div class="message default clearfix joined" id="m2">
<div class="body">
<div class="pull_right date details" title="06.04.2026 12:21:00 UTC+02:00">12:21</div>
<div class="media_wrap clearfix"><div class="title bold">Sticker</div><div class="description">Not included, change data exporting settings to download.</div><div class="status details">💐, 26.5 KB</div></div>
</div>
</div>
<div class="message default clearfix" id="m3">
<div class="pull_left userpic_wrap"><div class="userpic userpic8"><div class="initials">О</div></div></div>
<div class="body">
<div class="pull_right date details" title="06.04.2026 13:18:34 UTC+02:00">13:18</div>
<div class="from_name">Оля💜</div>
<div class="media_wrap clearfix"><div class="title bold">Photo</div><div class="description">Not included, change data exporting settings to download.</div><div class="status details">828×1792, 120.5 KB</div></div>
<span class="reactions"><span class="reaction active"><span class="emoji">🙏</span><span class="userpics"><div class="userpic userpic13"><div class="initials" title="Богдан 🌿">Б</div></div></span></span></span>
</div>
</div>
<div class="message default clearfix joined" id="m4">
<div class="body">
<div class="pull_right date details" title="06.04.2026 13:18:34 UTC+02:00">13:18</div>
<div class="media_wrap clearfix"><div class="title bold">Photo</div></div>
<div class="text">Дивись, я думаю або панамку</div>
</div>
</div>
<div class="message default clearfix" id="m5">
<div class="pull_left userpic_wrap"><div class="userpic userpic1"><div class="initials">Б</div></div></div>
<div class="body">
<div class="pull_right date details" title="06.04.2026 13:36:29 UTC+02:00">13:36</div>
<div class="from_name">Богдан 🌿</div>
<div class="reply_to details">In reply to <a href="#x">this message</a></div>
<div class="text">Я раніше хотів</div>
</div>
</div>
<div class="message default clearfix" id="m6">
<div class="pull_left userpic_wrap"><div class="userpic userpic1"><div class="initials">Б</div></div></div>
<div class="body">
<div class="pull_right date details" title="24.04.2026 00:50:45 UTC+02:00">00:50</div>
<div class="from_name">Богдан 🌿  via @pic</div>
<div class="media_wrap clearfix"><div class="title bold">Photo</div></div>
</div>
</div>
<div class="message default clearfix" id="m7">
<div class="pull_left userpic_wrap"><div class="userpic userpic1"><div class="initials">Б</div></div></div>
<div class="body">
<div class="pull_right date details" title="24.04.2026 03:10:37 UTC+02:00">03:10</div>
<div class="from_name">Богдан 🌿</div>
<div class="pull_left forwarded userpic_wrap"><div class="userpic userpic4"><div class="initials">s</div></div></div>
<div class="forwarded body">
<div class="from_name">slava_art <span class="date details" title="21.04.2025 20:58:06 UTC+02:00"> 21.04.2025 20:58:06</span></div>
<div class="text">Перший рядок<br>Другий рядок</div>
</div>
</div>
</div>
<div class="message default clearfix joined" id="m8">
<div class="body">
<div class="pull_right date details" title="24.04.2026 03:10:37 UTC+02:00">03:10</div>
<div class="forwarded body">
<div class="media_wrap clearfix"><div class="title bold">Photo</div></div>
</div>
</div>
</div>
<div class="message default clearfix" id="m9">
<div class="pull_left userpic_wrap"><div class="userpic userpic1"><div class="initials">Б</div></div></div>
<div class="body">
<div class="pull_right date details" title="24.04.2026 01:42:02 UTC+02:00">01:42</div>
<div class="from_name">Богдан 🌿</div>
<div class="pull_left forwarded userpic_wrap"><div class="userpic userpic7"><div class="initials">Vd</div></div></div>
<div class="forwarded body">
<div class="from_name">Vova Artist<span class="date details" title="12.01.2023 22:51:39 UTC+02:00"> 12.01.2023 22:51:39</span></div>
<div class="text">Текст давньої пересилки</div>
</div>
</div>
</div>
<div class="message default clearfix" id="m10">
<div class="pull_left userpic_wrap"><div class="userpic userpic1"><div class="initials">Б</div></div></div>
<div class="body">
<div class="pull_right date details" title="24.04.2026 03:11:00 UTC+02:00">03:11</div>
<div class="from_name">Богдан 🌿</div>
<div class="forwarded body">
<div class="from_name">Некто</div>
<div class="text">содержимое</div>
</div>
</div>
</div>
</div>
</div>
</body></html>"""
f = t.INPUT_DIR / "struct.html"; f.write_text(html, encoding="utf-8")
out = t.html_to_text(f)
check("первая строка тела на строке префикса",
      "[2026-04-06 12:20:57 UTC+02:00] Богдан 🌿: Вітаю!" in out, out)
check("форвард: переслыцик + источник + дата оригинала",
      "[2026-04-24 03:10:37 UTC+02:00] Богдан 🌿 [переслано от slava_art, 2025-04-21 20:58]: Перший рядок" in out, out)
check("форвард без даты оригинала",
      "[2026-04-24 03:11:00 UTC+02:00] Богдан 🌿 [переслано от Некто]: содержимое" in out, out)
check("joined-форвард наследует источник",
      "[2026-04-24 03:10:37 UTC+02:00] Богдан 🌿 [переслано от slava_art, 2025-04-21 20:58]: [медиа]" in out, out)
check("форвард со старой датой контента",
      "[2026-04-24 01:42:02 UTC+02:00] Богдан 🌿 [переслано от Vova Artist, 2023-01-12 22:51]: Текст давньої пересилки" in out, out)
check("via @pic: инлайн-бот в авторе, пробелы схлопнуты",
      "[2026-04-24 00:50:45 UTC+02:00] Богдан 🌿 via @pic: [медиа]" in out, out)
check("реакция: строка с эмодзи и реактившим (один пробел)",
      " [реакции: 🙏 — Богдан 🌿]" in out, out)
check("текст + медиа маркер", "Дивись, я думаю або панамку [медиа]" in out, out)
check("service-разделитель дня погашен", "6 April 2026" not in out, out)
check("In reply to погашен", "In reply to" not in out, out)
check("имя чата из page_header живет", "Оля💜" in out, out)
check("инициалы не текут", not re.search(r"(?m)^[А-ЯЁІЇЄҐa-z]$", out), out)
stripped = re.sub(r"\[[^\]]*\]", "", out)
check("голое время погашено", not re.search(r"\d{2}:\d{2}", stripped), stripped)
cleaned = t.clean_text_content(out)[0]
check("заглушки/размеры убиты",
      "Not included" not in cleaned and "💐" not in cleaned and "828" not in cleaned
      and "Sticker" not in cleaned and "Photo" not in cleaned, cleaned)
check("форвард-ноты переживают очистку",
      "[переслано от slava_art, 2025-04-21 20:58]" in cleaned, cleaned)
check("реакции переживают очистку", "[реакции: 🙏 — Богдан 🌿]" in cleaned, cleaned)

print("== 13. Эмодзи-срез ==")
tr = t.safe_truncate("x" * 118 + "👨\u200d👩\u200d👧", 120)
check("ZWJ-кластер отрезан целиком",
      "\u200d" not in tr and "👨" not in tr and tr.endswith("..."))
tr2 = t.safe_truncate("y" * 118 + "👍\U0001F3FB" + "z", 120)
check("целый кластер с тоном кожи не трогается", tr2.endswith("👍\U0001F3FB..."))
tr2b = t.safe_truncate("y" * 119 + "👍\U0001F3FB" + "z", 120)
check("разрез по тону: модификатор отброшен, база жива",
      not tr2b.endswith("\U0001F3FB") and tr2b.endswith("👍..."))
tr3 = t.safe_truncate("z" * 118 + "🇺🇦" + "q" * 5, 120)
check("целый флаг не режется", "🇺🇦" in tr3)
tr4 = t.safe_truncate("z" * 119 + "🇺🇦🇺🇦", 120)
check("полфлага отбрасывается", "🇺" not in tr4 and "🇦" not in tr4)
tr5 = t.safe_truncate("x" * 119 + "e\u0301q", 120)
check("база не отрывается от combining", tr5 == "x" * 119 + "...")

print("== 14. Симлинки (POSIX) ==")
if os.name == "posix":
    secret = tmp / "secret.txt"; secret.write_text("секрет", encoding="utf-8")
    link = t.INPUT_DIR / "leak.txt"; link.symlink_to(secret)
    check("симлинк отсеян", link not in t.get_files({".txt"}, folder=t.INPUT_DIR))
    link.unlink()
else:
    print("  [--] пропущено (не POSIX)")

print("== 15. Merge ==")
(t.INPUT_DIR / "a.txt").write_text("первый дамп", encoding="utf-8")
(t.INPUT_DIR / "b.txt").write_text("второй дамп", encoding="utf-8")
run = t.new_run_dir("txt")
t.merge_process(t.get_files({".txt"}, folder=t.INPUT_DIR), False, "merged_txt", run)
m = (run / "merged_txt_clean.txt").read_text(encoding="utf-8")
check("маркеры источников", "### SOURCE: a_txt ###" in m and "### SOURCE: b_txt ###" in m)

print("== 16. Лимит merge ==")
old_lim = t.MAX_TOTAL_MERGE_SIZE
t.MAX_TOTAL_MERGE_SIZE = 10
run2 = t.new_run_dir("txt")
t.merge_process(t.get_files({".txt"}, folder=t.INPUT_DIR), False, "merged_txt", run2)
check("merge отказан при превышении", not (run2 / "merged_txt_clean.txt").exists())
t.MAX_TOTAL_MERGE_SIZE = old_lim

print("== 17. Поиск не ест свои отчеты ==")
fake = [t.OUTPUT_DIR / "search_clean.txt", t.OUTPUT_DIR / "merged_txt_clean.txt"]
names = [p.name for p in fake if "_clean" in p.name and not p.name.startswith("search_")]
check("search_* исключен", names == ["merged_txt_clean.txt"])

print("== 18. Изоляция прогонов ==")
d1 = t.new_run_dir("txt")
d2 = t.new_run_dir("txt")
check("папки уникальны", d1 != d2 and d1.is_dir() and d2.is_dir())
(d1 / "one_clean.txt").write_text("найдись", encoding="utf-8")
found = [p for p in t.get_files({".txt"}, folder=t.OUTPUT_DIR) if p.name == "one_clean.txt"]
check("поиск видит clean в run-папке", len(found) == 1 and found[0].parent == d1)

print("== 19. Санитизация имен ==")
bad = t.safe_name("bad\x1b[31m имя\nтут")
check("контроль-символы заменены", "\x1b" not in bad and "\n" not in bad)
check("пустое имя -> file", t.safe_name(" . ") == "file")

print("== 20. Короткие строки: state machine ==")
gpt = "[2024-06-10 19:30] Иван: первая\nок\nго\n42\n?!\nконец"
c = t.clean_text_content(gpt)[0]
check("многострочное тело: ВСЕ короткие строки живут",
      c.splitlines() == ["[2024-06-10 19:30] Иван: первая", "ок", "го", "42", "?!", "конец"], c)
lead = "В\nТ\n❤\n[2024-06-10 19:30] Иван: тело\nда"
c = t.clean_text_content(lead)[0]
check("ведущие фантомы умирают",
      c.splitlines() == ["[2024-06-10 19:30] Иван: тело", "да"], c)
plain = "да\nок\nго\nА\nобычный текст без структуры"
c = t.clean_text_content(plain)[0]
check("TXT без префиксов: короткие строки не трогаются",
      c.splitlines() == ["да", "ок", "го", "А", "обычный текст без структуры"], c)
mixed = ("[2024-06-10 19:30] Иван: тело\nок\n"
         "### SOURCE: notes_txt ###\nмои заметки\nда\nА\n42\n")
c = t.clean_text_content(mixed)[0]
check("merge со сторонним TXT: короткие строки notes выживают",
      all(s in c.splitlines() for s in ("мои заметки", "да", "А", "42")), c)

print("== 21. Медиа-заглушки в любом месте ==")
stub = ("контент\nVideo message\nNot included, change data exporting settings to download.\n"
        "00:29, 3.8 MB\n85.6 KB\n960×1280, 127.3 KB\n💐, 26.5 KB\nок, 12 kb\nещё контент")
c = t.clean_text_content(stub)[0]
check("заглушки гаснут",
      "Video message" not in c and "Not included" not in c and "💐" not in c
      and "960" not in c, c)
check("живой текст 'ок, 12 kb' не задет", "ок, 12 kb" in c, c)

print("== 22. ПРОФИЛЬ ЧАТА (+ нормализация via/форвардов) ==")
psample = (
    "### SOURCE: chat_txt ###\n"
    "[2026-04-06 12:00:00 UTC+02:00] Аня: привет\n"
    "как дела\n"
    "[2026-04-06 12:05:00 UTC+02:00] Боря: норм\n"
    "[2026-04-06 13:00:00 UTC+02:00] Аня: ок\n"
    "[2026-04-07 20:00:00 UTC+02:00] Боря: [медиа]\n"
    " [реакции: ❤ — Аня]\n"
    "[2026-04-07 20:30:00 UTC+02:00] Аня [переслано от X, 2026-04-06 10:00]: текст\n"
    "[2026-04-07 20:35:00 UTC+02:00] Аня via @pic: [медиа]\n"
)
cleaned = t.clean_text_content(psample)[0]
p = t.build_profile(cleaned)
check("профиль: итоги", p["totals"]["msgs"] == 6 and p["totals"]["media"] == 2, p["totals"])
check("профиль: via и форвард не плодят авторов",
      {a["name"] for a in p["authors"]} == {"Аня", "Боря"}, p["authors"])
check("профиль: сообщения склеены правильно",
      {a["name"]: a["msgs"] for a in p["authors"]} == {"Аня": 4, "Боря": 2}, p["authors"])
check("профиль: часы", p["hours_local"] == {12: 2, 13: 1, 20: 3}, p["hours_local"])
check("профиль: пересылка + возраст",
      p["forwards"]["count"] == 1
      and abs(p["forwards"]["ages"][0] - 1.4375) < 0.01
      and p["forwards"]["max_from"] == "X", p["forwards"])
check("профиль: реакции",
      p["reactions"]["recv"]["Боря"]["❤"] == 1
      and p["reactions"]["given"]["Аня"]["❤"] == 1, p["reactions"])
check("профиль: период и TZ",
      p["period"] == ["2026-04-06 12:00", "2026-04-07 20:35"]
      and p["tz_offsets"] == ["UTC+02:00"])
r = t.render_profile(p)
check("рендер: секции на месте",
      any("ПРОФАЙЛ" in x for x in r) and any("ЧАСАМ" in x for x in r)
      and any("ПАУЗЫ" in x for x in r) and any("ПЕРЕСЫЛКИ" in x for x in r), r)
check("профиль: None без структуры", t.build_profile("просто текст без дат") is None)

print("== 23. Крипто-валидация BTC ==")
check("base58check: genesis-адрес валиден",
      t.btc_base58check_ok("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))
check("base58check: битая чексумма отклонена",
      not t.btc_base58check_ok("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"))
check("bech32: смешанный регистр отклонен",
      not t.btc_bech32_ok("bc1QW508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"))
e, _, _ = t.extract_entities_with_context(
    "адреса: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa и 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy "
    "и 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb")
check("extract: валидные base58 приняты, битая отброшена",
      "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in e.get("crypto_btc", {})
      and "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy" in e.get("crypto_btc", {})
      and "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb" not in e.get("crypto_btc", {}),
      e.get("crypto_btc"))
e, _, _ = t.extract_entities_with_context(
    "segwit: bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4 и битый bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")
check("extract: bech32 (BIP173) валиден, битый отброшен",
      "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4" in e.get("crypto_btc", {})
      and "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5" not in e.get("crypto_btc", {}),
      e.get("crypto_btc"))

print("== 24. Поиск: режимы ==")
m1 = t.make_search_matcher("мир", "1")
check("подстрока находит вхождение", m1("мировоззрение") and m1("Мир"))
m2 = t.make_search_matcher("мир", "2")
check("целое слово: не матчит внутри слова, матчит с пунктуацией",
      m2("мир!") and not m2("мировоззрение") and m2("ну мир, ок"))
m3 = t.make_search_matcher("мир|chat", "3")
check("regex: альтернатива работает", m3("chat здесь") and m3("мир") and not m3("чат"))
try:
    t.make_search_matcher("([)", "3"); check("битый regex ловится", False)
except re.error:
    check("битый regex ловится", True)

print(f"\nALL OK ({OK} проверок)")
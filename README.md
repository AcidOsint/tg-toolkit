#  tg_toolkit Q1 (v6.7)

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![Zero Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)

> **🇺🇦 UA:** OSINT-профайлінг експортів Telegram: зшивка, очистка, структурний парсинг, вилучення сутностей, пошук. Чат можуть видалити, до акаунта — втратити доступ. Експорт Telegram Desktop — єдиний повний знімок переписки, але сирий HTML нечитабельний і не шукається. `tg_toolkit` перетворює його на читабельний лог і дістає профайлінг-сутності.
> 
> **🇬🇧 EN:** OSINT profiling for Telegram exports: merging, noise cleaning, structural parsing, entity extraction, and local grep search. A raw Telegram Desktop HTML export is unreadable and hard to parse. `tg_toolkit` converts it into a clean, chronological log and extracts actionable profiling entities.

<img width="680" height="346" alt="photo_2026-09-19_21-21-04" src="https://github.com/user-attachments/assets/e165e439-856a-499c-abe2-77acbef622d1" />

## 🔥 Features
* **Zero Dependencies:** Pure Python. No `pip install` required. Drop and run.
* **Smart HTML Parsing:** Converts messy Telegram HTML exports into clean `[YYYY-MM-DD HH:MM] Author: Text` format.
* **Noise Reduction:** Automatically removes system messages (joined, left, pinned, exported from) and empty media stubs.
* **Entity Extraction:** Extracts and saves Telegram tags, T.me links, URLs, Emails, Phones, Crypto Wallets (BTC, ETH, TRX), IPv4, and Credit Cards.
* **Safe Merging:** Safely merges multiple chats into a single chronological timeline without breaking data.
* **Excel-Ready Reports:** Exports entities to JSON, TXT, and `utf-8-sig` CSV (perfect for MS Excel).
* **Local Grep Search:** Fast text search across all processed reports without memory leaks.

## 🚀 Quick Start

1. **Download the tool:**
   Clone the repository or download the `.zip` archive.
   ```bash
   git clone https://github.com/AcidOsint/tg-toolkit.git

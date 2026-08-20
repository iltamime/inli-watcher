#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Surveillance des nouvelles annonces in'li.fr (Île-de-France, loyer max défini)
avec notification Telegram + Email dès qu'une nouvelle annonce apparaît.
"""

import json
import os
import re
import smtplib
import time
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

IDF_DEPARTEMENTS = [
    "paris_d:75",
    "paris-departement_d:75",
    "seine-et-marne_d:77",
    "seine-et-marne-departement_d:77",
    "yvelines_d:78",
    "yvelines-departement_d:78",
    "essonne_d:91",
    "essonne-departement_d:91",
    "hauts-de-seine_d:92",
    "hauts-de-seine-departement_d:92",
    "seine-saint-denis_d:93",
    "seine-saint-denis-departement_d:93",
    "val-de-marne_d:94",
    "val-de-marne-departement_d:94",
    "val-d-oise_d:95",
    "val-d-oise-departement_d:95",
]

LOYER_MAX = int(os.environ.get("LOYER_MAX", "760"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

STATE_FILE = "inli_seen_ids.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

BASE_URL = "https://www.inli.fr/locations/offres/"


def load_seen_ids():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(seen_ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


def parse_price(text):
    match = re.search(r"([\d\s]+)\s*€", text)
    if not match:
        return None
    number = match.group(1).replace(" ", "").replace("\u202f", "").strip()
    try:
        return int(number)
    except ValueError:
        return None


def fetch_listings_for_department(dept_slug):
    listings = []
    page = 1
    while True:
        url = f"{BASE_URL}{dept_slug}/"
        params = {"page": page} if page > 1 else {}
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        except requests.RequestException as e:
            print(f"  [!] Erreur reseau sur {dept_slug} page {page}: {e}")
            break

        if resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.select('a[href*="/locations/offre/"]')

        if not links:
            break

        found_on_page = 0
        for a in links:
            href = a.get("href", "")
            href_clean = href.split("?")[0].rstrip("/")
            listing_id = href_clean.split("/")[-1]
            if not listing_id:
                continue
            title_text = a.get_text(" ", strip=True)
            price = parse_price(title_text)

            listings.append(
                {
                    "id": listing_id,
                    "title": title_text,
                    "price": price,
                    "url": href if href.startswith("http") else f"https://www.inli.fr{href}",
                }
            )
            found_on_page += 1

        if found_on_page == 0:
            break

        page += 1
        if page > 30:
            break
        time.sleep(1)

    return listings


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except requests.RequestException as e:
        print(f"  [!] Erreur envoi Telegram: {e}")


def send_email(subject, body):
    if not EMAIL_ENABLED or not EMAIL_FROM or not EMAIL_PASSWORD:
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
    except Exception as e:
        print(f"  [!] Erreur envoi email: {e}")


def check_once(seen_ids):
    new_listings = []

    for dept in IDF_DEPARTEMENTS:
        listings = fetch_listings_for_department(dept)
        within_budget = [l for l in listings if l["price"] is not None and l["price"] <= LOYER_MAX]
        print(f"  -> {dept} : {len(listings)} annonce(s) au total, "
              f"{len(within_budget)} dans le budget ({LOYER_MAX}€ max)")

        for listing in listings:
            if listing["id"] in seen_ids:
                continue
            if listing["price"] is not None and listing["price"] > LOYER_MAX:
                continue
            new_listings.append(listing)
            seen_ids.add(listing["id"])

    return new_listings, seen_ids


def main():
    print("=== Surveillance in'li.fr - Île-de-France, loyer max", LOYER_MAX, "€ ===")
    seen_ids = load_seen_ids()
    first_run = len(seen_ids) == 0

    if first_run:
        print("Premier lancement : on enregistre les annonces déjà en ligne "
              "sans notifier (pour ne pas te spammer avec l'existant).")

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Vérification en cours...")
    new_listings, seen_ids = check_once(seen_ids)
    save_seen_ids(seen_ids)

    if first_run:
        print(f"{len(new_listings)} annonces existantes enregistrées.")
    elif new_listings:
        print(f"{len(new_listings)} nouvelle(s) annonce(s) trouvée(s) !")
        for listing in new_listings:
            message = (
                f"🏠 Nouvelle annonce in'li !\n"
                f"{listing['title']}\n"
                f"{listing['url']}"
            )
            print("  ->", message)
            send_telegram(message)
            send_email("Nouvelle annonce in'li", message)
    else:
        print("Aucune nouvelle annonce cette fois.")


if __name__ == "__main__":
    main()

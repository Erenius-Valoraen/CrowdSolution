"""
Seed script for UPSTREAM server database.
Populates realistic verification data:
- Scam patterns from CAFC, FTC, and university housing warnings
- Rental listings and duplicate signatures
- Local rent baselines for student postal codes
- Verified entities directory
- Verified economic indicator series
"""
from __future__ import annotations

import json
from services.api.db import get_connection, init_db


def seed_database() -> None:
    init_db()
    conn = get_connection()
    try:
        with conn:
            # 1. SCAM PATTERNS
            conn.execute("DELETE FROM scam_patterns")
            patterns = [
                (
                    "pat_etransfer_before_viewing",
                    "rental",
                    "E-Transfer / Deposit Before In-Person Viewing",
                    "Landlord demands first/last month deposit, key deposit, or holding fee via e-transfer before allowing an in-person viewing.",
                    json.dumps([
                        "deposit before viewing", "etransfer", "e-transfer", "send money to hold",
                        "wire transfer to reserve", "holding deposit", "first and last before visit",
                        "secure the unit before seeing", "deposit to arrange viewing"
                    ]),
                    json.dumps([
                        "Demanding payment before in-person or live video viewing",
                        "Claiming high demand and requiring an immediate e-transfer to 'hold' the key",
                        "Refusing to meet in person or do a walkthrough"
                    ]),
                    "Canadian Anti-Fraud Centre (CAFC)",
                    "https://antifraudcentre-centreantifraude.ca/scams-fraudes/rental-locative-eng.htm"
                ),
                (
                    "pat_absent_landlord",
                    "rental",
                    "Absent / Out-of-Country Landlord with Mailed Keys",
                    "Alleged owner claims they are currently abroad (missionary, military, international agency) and promises to courier keys once payment clears.",
                    json.dumps([
                        "out of the country", "keys will be mailed", "missionary", "relocated for work",
                        "courier the keys", "fedex the keys", "keys via dhl", "cannot meet because i am away",
                        "currently overseas"
                    ]),
                    json.dumps([
                        "Landlord claims they cannot show the unit because they are out of the country",
                        "Promises to courier/mail keys after funds are sent",
                        "Fabricates an elaborate sympathetic or prestigious backstory"
                    ]),
                    "FTC Consumer Advice",
                    "https://consumer.ftc.gov/articles/rental-scams"
                ),
                (
                    "pat_off_platform_urgency",
                    "rental",
                    "Off-Platform Contact & Artificial Urgency",
                    "Seller pressures user to switch immediately to WhatsApp/Telegram and demands money within hours, claiming other buyers are waiting.",
                    json.dumps([
                        "text me on whatsapp", "contact me on telegram", "pay within 24 hours",
                        "someone else will take it today", "urgent decision", "whatsapp only",
                        "move conversation to whatsapp"
                    ]),
                    json.dumps([
                        "Moving communication off the verified platform or marketplace",
                        "Artificial urgency forcing quick, unverified financial transfers",
                        "Unwillingness to provide standard written provincial lease"
                    ]),
                    "UW Off-Campus Housing Advisory",
                    "https://uwaterloo.ca/off-campus-housing/scams"
                ),
                (
                    "pat_job_training_deposit",
                    "job",
                    "Upfront Training / Ambassador Deposit",
                    "Recruiter offers a student ambassador, remote assistant, or campus rep role but requires the student to pay an upfront fee for training, onboarding, or equipment.",
                    json.dumps([
                        "training deposit", "campus ambassador fee", "equipment deposit",
                        "starter kit fee", "pay for background check", "refundable training fee",
                        "deposit for supplies"
                    ]),
                    json.dumps([
                        "Legitimate employers never charge candidates for job placement, training, or equipment",
                        "Recruiter contacted via social media DM with no corporate email address",
                        "Payment requested via e-transfer, crypto, or gift card"
                    ]),
                    "Canadian Anti-Fraud Centre (CAFC)",
                    "https://antifraudcentre-centreantifraude.ca/scams-fraudes/job-emploi-eng.htm"
                ),
                (
                    "pat_excessive_key_deposit",
                    "lease_clause",
                    "Illegal Damage Deposit or Excessive Key Fee",
                    "Landlord demands a damage deposit, cleaning deposit, or key deposit exceeding direct replacement cost (illegal under Ontario RTA).",
                    json.dumps([
                        "damage deposit", "cleaning fee", "key deposit $500", "security deposit",
                        "non-refundable deposit", "cleaning charge"
                    ]),
                    json.dumps([
                        "In Ontario, landlords may only require first and last month's rent. Damage deposits are illegal under the Residential Tenancies Act (RTA).",
                        "Key deposits must be strictly refundable and cannot exceed actual replacement cost (typically $15-$50)."
                    ]),
                    "Ontario Landlord and Tenant Board (LTB)",
                    "https://tribunalsontario.ca/ltb/faqs/#faq4"
                ),
                (
                    "pat_sin_phishing",
                    "id_request",
                    "Pre-Lease SIN / Sensitive ID Mandate",
                    "Requiring Social Insurance Number (SIN) or banking login credentials prior to a signed lease agreement.",
                    json.dumps([
                        "provide your sin", "social insurance number", "bank login",
                        "sin number required", "full credit card number for application"
                    ]),
                    json.dumps([
                        "Landlords have no legal right to mandate your SIN. You can provide an Equifax/TransUnion report directly.",
                        "Demanding banking passwords or confidential government IDs before any lease is offered"
                    ]),
                    "Office of the Privacy Commissioner of Canada",
                    "https://www.priv.gc.ca/en/privacy-topics/identity-theft/social-insurance-numbers/"
                ),
            ]
            conn.executemany(
                """
                INSERT INTO scam_patterns (
                    pattern_id, scam_type, pattern_name, description, keywords, red_flags, source, evidence_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                patterns,
            )

            # 2. LISTINGS (with known duplicate signatures to test detection)
            conn.execute("DELETE FROM listings")
            listings = [
                (
                    "lst_legit_01",
                    "Kijiji",
                    "https://kijiji.ca/v-apartments/waterloo/1-bed-sublet-lester-st/1001",
                    "Modern 1-Bedroom Sublet near UW Campus on Lester St",
                    "Subletting 1 bedroom in a 5x5 apartment on Lester St. En-suite bathroom, high-speed internet included. Available for Fall/Winter term. In-person viewings welcome after 5 PM.",
                    "201 Lester St, Waterloo, ON",
                    "N2L",
                    "Waterloo",
                    1450.0,
                    1,
                    "student.sublet.lester@gmail.com",
                    "519-555-0141",
                    json.dumps(["img_lester_bedroom_01", "img_lester_kitchen_02"]),
                ),
                (
                    "lst_legit_02",
                    "Facebook Marketplace",
                    "https://facebook.com/marketplace/item/2002",
                    "Spacious 2 Bed Apartment on Columbia St West",
                    "2 bedroom unit available immediately. Utilities extra, hydro included. Walking distance to University of Waterloo and Wilfrid Laurier. Official lease transfer.",
                    "130 Columbia St W, Waterloo, ON",
                    "N2L",
                    "Waterloo",
                    2200.0,
                    2,
                    "leasing@accommod8u.com",
                    "519-555-0188",
                    json.dumps(["img_columbia_living_01"]),
                ),
                (
                    "lst_legit_03",
                    "BAM",
                    "https://bam.uwaterloo.ca/listings/3003",
                    "Single Room in Student House on Hazel St",
                    "1 private room in clean student home on Hazel St. 10 minute walk to Laurier and 15 minute walk to UW. All utilities and internet included. In-person walkthrough required before signing.",
                    "45 Hazel St, Waterloo, ON",
                    "N2L",
                    "Waterloo",
                    900.0,
                    1,
                    "landlord.hazel@uwaterloo-housing.ca",
                    "519-555-0112",
                    json.dumps(["img_hazel_room_01"]),
                ),
                # DUPLICATE CLUSTER (Same villain listing posted at multiple addresses & prices)
                (
                    "lst_scam_dup1",
                    "Facebook Marketplace",
                    "https://facebook.com/marketplace/item/4001",
                    "Cozy 1 Bedroom luxury apartment fully furnished with all utilities included gym and pool",
                    "Beautiful modern 1-bedroom luxury suite, fully furnished with designer finishes. Hydro, water, AC and gigabit WiFi all included. Stainless steel appliances, parking spot included. Deposit required immediately by e-transfer to hold keys.",
                    "135 Columbia St W, Waterloo, ON",
                    "N2L",
                    "Waterloo",
                    850.0,  # Suspiciously cheap for 1-bed
                    1,
                    "rentals.mark.uw@gmail.com",
                    "519-555-0199",
                    json.dumps(["img_scam_luxury_living", "img_scam_bedroom"]),
                ),
                (
                    "lst_scam_dup2",
                    "Kijiji",
                    "https://kijiji.ca/v-apartments/waterloo/luxury-1-bed/4002",
                    "Cozy 1 Bedroom luxury apartment fully furnished with all utilities included gym and pool",
                    "Beautiful modern 1-bedroom luxury suite, fully furnished with designer finishes. Hydro, water, AC and gigabit WiFi all included. Stainless steel appliances, parking spot included. Currently out of town, courier keys upon e-transfer.",
                    "220 Lester St, Waterloo, ON",
                    "N2L",
                    "Waterloo",
                    950.0,  # Same photos & text, different address and price!
                    1,
                    "rentals.mark.uw@gmail.com",
                    "519-555-0199",
                    json.dumps(["img_scam_luxury_living", "img_scam_bedroom"]),
                ),
                (
                    "lst_scam_dup3",
                    "Craigslist",
                    "https://kitchener.craigslist.org/apa/d/cozy-1-bedroom-luxury/4003.html",
                    "Cozy 1 Bedroom luxury apartment fully furnished with all utilities included gym and pool",
                    "Beautiful modern 1-bedroom luxury suite, fully furnished with designer finishes. Hydro, water, AC and gigabit WiFi all included. Urgent moving sale.",
                    "330 King St N, Waterloo, ON",
                    "N2J",
                    "Waterloo",
                    750.0,  # Third address, third price!
                    1,
                    "rentals.mark.uw@gmail.com",
                    "519-555-0199",
                    json.dumps(["img_scam_luxury_living", "img_scam_bedroom"]),
                ),
            ]
            conn.executemany(
                """
                INSERT INTO listings (
                    listing_id, platform, url, title, body_text, address, postal_prefix, city, price, bedrooms, contact_email, contact_phone, image_hashes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                listings,
            )

            # 3. LOCAL BASELINES (Waterloo & Student Housing Hubs)
            conn.execute("DELETE FROM local_baselines")
            baselines = [
                ("N2L", 1, "Waterloo (Northdale / UW / Laurier)", 1400.0, 1150.0, 1750.0, 480),
                ("N2L", 2, "Waterloo (Northdale / UW / Laurier)", 2150.0, 1800.0, 2600.0, 320),
                ("N2L", 5, "Waterloo (Northdale 5-bed suite room)", 900.0, 750.0, 1050.0, 560),
                ("N2J", 1, "Waterloo (Uptown)", 1480.0, 1200.0, 1850.0, 290),
                ("N2J", 2, "Waterloo (Uptown)", 2250.0, 1900.0, 2700.0, 210),
                ("N2T", 1, "Waterloo (West)", 1350.0, 1100.0, 1650.0, 190),
                ("M5S", 1, "Toronto (Downtown / UofT)", 2450.0, 2100.0, 2950.0, 850),
            ]
            conn.executemany(
                """
                INSERT INTO local_baselines (
                    postal_prefix, bedrooms, city, median_price, p10_price, p90_price, sample_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                baselines,
            )

            # 4. ENTITIES (Verified property management vs fake)
            conn.execute("DELETE FROM entities")
            entities = [
                (
                    "rez-one",
                    "Rez-One Properties",
                    "property_mgmt",
                    True,
                    "Ontario, Canada",
                    "2012-05-14",
                    "https://www.appmybizaccount.gov.on.ca/",
                    "Major student housing provider in Waterloo (Fergus House, Blair House, Hespeler House, Preston House).",
                ),
                (
                    "accommod8u",
                    "Accommod8u Property Management",
                    "property_mgmt",
                    True,
                    "Ontario, Canada",
                    "2014-08-20",
                    "https://www.appmybizaccount.gov.on.ca/",
                    "Large rental operator along University Ave and Columbia St in Waterloo.",
                ),
                (
                    "wcri",
                    "Waterloo Co-operative Residence Inc.",
                    "landlord",
                    True,
                    "Ontario, Canada",
                    "1964-03-01",
                    "https://www.appmybizaccount.gov.on.ca/",
                    "Member-owned student housing co-op on University Ave.",
                ),
                (
                    "schembri",
                    "Schembri Property Management",
                    "property_mgmt",
                    True,
                    "Ontario, Canada",
                    "2007-11-03",
                    "https://www.appmybizaccount.gov.on.ca/",
                    "Commercial student apartment manager in Waterloo region.",
                ),
                (
                    "mark_rentals",
                    "Mark Rentals",
                    "landlord",
                    False,
                    "None",
                    None,
                    None,
                    "Unregistered individual. No business number or corporate registry found.",
                ),
            ]
            conn.executemany(
                """
                INSERT INTO entities (
                    entity_key, entity_name, entity_type, registered, jurisdiction, incorporated_on, official_registry_url, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                entities,
            )

            # 5. ECONOMIC INDICATORS (Statistical Fact-Checking)
            conn.execute("DELETE FROM economic_indicators")
            indicators = [
                ("LNS14000000.M_SA", "Unemployment Rate", "Monthly", "Fraction", "Bureau of Labor Statistics", "2025-01-01", 0.040, "2025-02-07"),
                ("LNS14000000.M_SA", "Unemployment Rate", "Monthly", "Fraction", "Bureau of Labor Statistics", "2025-06-01", 0.041, "2025-07-03"),
                ("LNS14000000.M_SA", "Unemployment Rate", "Monthly", "Fraction", "Bureau of Labor Statistics", "2026-01-01", 0.043, "2026-02-06"),
                ("CUSRSA0SA01982-84.M", "Consumer Price Index (CPI All Items)", "Monthly", "Index", "Bureau of Labor Statistics", "2025-01-01", 315.6, "2025-02-12"),
                ("CUSRSA0SA01982-84.M", "Consumer Price Index (CPI All Items)", "Monthly", "Index", "Bureau of Labor Statistics", "2026-01-01", 324.8, "2026-02-11"),
                ("BEA_NIPA_1.1.1_A191RL_Q", "Real GDP Growth", "Quarterly", "Percent Change", "Bureau of Economic Analysis", "2025-01-01", 2.8, "2025-04-24"),
                ("BEA_NIPA_1.1.1_A191RL_Q", "Real GDP Growth", "Quarterly", "Percent Change", "Bureau of Economic Analysis", "2025-10-01", 2.3, "2026-01-29"),
            ]
            conn.executemany(
                """
                INSERT INTO economic_indicators (
                    variable, variable_name, frequency, unit, source, date, value, published_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                indicators,
            )

    finally:
        conn.close()
    print("Database successfully seeded at", conn)


if __name__ == "__main__":
    seed_database()


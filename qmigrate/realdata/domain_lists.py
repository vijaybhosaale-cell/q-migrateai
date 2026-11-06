"""Real organisations' public websites, grouped by sector.

These are just names of public websites. Everything else (algorithms, certificates, hosting cloud, the
certificate authorities they depend on) is measured live from the internet when discovery runs.

The sector profile sets the two things the internet cannot tell us: how sensitive the data behind
the site is and how long it must stay confidential. The values are sector assumptions, shown here so
they can be changed: banks keep customer and transaction records for 5-10 years (anti-money-laundering
rules), hospitals keep patient records for 20 years or more.
"""

FINANCE = [
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com", "hsbc.com", "barclays.co.uk", "lloydsbank.com",
    "natwest.com", "santander.com", "bnpparibas.com", "societegenerale.com", "credit-agricole.com", "ing.com",
    "deutsche-bank.de", "commerzbank.de", "ubs.com", "rabobank.nl", "abnamro.nl", "unicredit.it",
    "intesasanpaolo.com", "bbva.com", "caixabank.com", "nordea.com", "revolut.com", "n26.com", "monzo.com",
    "paypal.com", "stripe.com", "visa.com", "mastercard.com", "americanexpress.com", "adyen.com", "wise.com",
    "klarna.com", "goldmansachs.com", "morganstanley.com", "schwab.com", "fidelity.com", "ecb.europa.eu",
    "bankofengland.co.uk", "banque-france.fr", "swift.com", "sbi.co.in", "hdfcbank.com", "icicibank.com",
]

HEALTH = [
    "nhs.uk", "who.int", "cdc.gov", "nih.gov", "mayoclinic.org", "clevelandclinic.org", "hopkinsmedicine.org",
    "kaiserpermanente.org", "mountsinai.org", "nyulangone.org", "massgeneral.org", "stanfordhealthcare.org",
    "ucsfhealth.org", "uclahealth.org", "mdanderson.org", "cancer.gov", "medlineplus.gov", "webmd.com",
    "healthline.com", "epic.com", "athenahealth.com", "philips.com", "siemens-healthineers.com", "gehealthcare.com",
    "pfizer.com", "novartis.com", "roche.com", "sanofi.com", "astrazeneca.com", "gsk.com", "ema.europa.eu",
    "fda.gov", "ameli.fr", "aphp.fr", "charite.de", "doctolib.fr", "teladochealth.com", "unitedhealthgroup.com",
    "cvs.com", "walgreens.com", "labcorp.com", "questdiagnostics.com", "apollohospitals.com",
]

# Used only when the Tranco list cannot be downloaded.
GENERAL = [
    "google.com", "cloudflare.com", "github.com", "wikipedia.org", "microsoft.com", "apple.com", "amazon.com",
    "aws.amazon.com", "azure.microsoft.com", "cloud.google.com", "login.microsoftonline.com", "accounts.google.com",
    "okta.com", "mozilla.org", "python.org", "openssl.org", "letsencrypt.org", "nist.gov", "bbc.co.uk",
    "nytimes.com", "whatsapp.com", "signal.org", "zoom.us", "salesforce.com", "dropbox.com", "linkedin.com",
    "netflix.com", "spotify.com", "adobe.com", "oracle.com",
]

# sensitivity 1-5, retention in years, business criticality 1-5 (rank-based criticality overrides it for Tranco)
SECTORS = {
    "finance": {"label": "Finance sector (banks, payments)", "domains": FINANCE, "sensitivity": 5, "retention": 10, "criticality": 5},
    "health": {"label": "Health sector (hospitals, health agencies, pharma)", "domains": HEALTH, "sensitivity": 5, "retention": 20, "criticality": 5},
    "tranco": {"label": "Most popular websites (Tranco top list)", "domains": GENERAL, "sensitivity": 3, "retention": 2, "criticality": 4},
    "custom": {"label": "Your own domains", "domains": [], "sensitivity": 4, "retention": 5, "criticality": 4},
}

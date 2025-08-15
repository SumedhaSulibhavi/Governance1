import sqlite3

# Connect to (or create) SQLite DB
conn = sqlite3.connect("data.db")
cursor = conn.cursor()

# ---- Create services table if it doesn't exist ----
cursor.execute("""
CREATE TABLE IF NOT EXISTS services (
    service_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    details TEXT NOT NULL
)
""")

# ---- List of services to insert ----
services_data = [
    ("revenue", "Revenue Department",
     "- Land Records: View and download your land ownership details.\n"
     "- Property Registration: Apply for and track property registration.\n"
     "- Income Certificates: Apply for income certificates.\n"
     "- Fee: ₹50-₹500 depending on service.\n"
     "- Processing Time: 3-7 working days.\n"
     "- Contact: revenue-office@state.gov.in"),

    ("municipal", "Municipal Services",
     "- Property Tax: Pay or check outstanding property taxes.\n"
     "- Water Supply: Apply for new connection or complaints.\n"
     "- Waste Management: Report uncollected garbage.\n"
     "- Fee: Variable.\n"
     "- Processing Time: 2-5 working days.\n"
     "- Contact: municipal-corporation@city.gov.in"),

    ("health", "Health Department",
     "- Medical Certificates: Apply for medical fitness/disability certificates.\n"
     "- Vaccination Records: Check immunization details.\n"
     "- Health Schemes: Learn about state and central health schemes.\n"
     "- Fee: Free for most services.\n"
     "- Processing Time: Immediate to 3 days.\n"
     "- Contact: health-dept@state.gov.in"),

    ("education", "Education Department",
     "- School Admissions: Apply for government and aided schools.\n"
     "- Scholarships: Check eligibility and apply online.\n"
     "- Educational Certificates: Duplicate or verification services.\n"
     "- Fee: Free or nominal.\n"
     "- Processing Time: 5-10 working days.\n"
     "- Contact: edu-dept@state.gov.in"),

    ("social_welfare", "Social Welfare Department",
     "- Pension Schemes: Apply for old-age or widow pensions.\n"
     "- Disability Certificates: Required for welfare benefits.\n"
     "- Welfare Programs: State-funded benefits for underprivileged groups.\n"
     "- Fee: Free.\n"
     "- Processing Time: 7-15 working days.\n"
     "- Contact: socialwelfare@state.gov.in"),

    ("agriculture", "Agriculture Department",
     "- Farmer Registration: Register for crop benefits.\n"
     "- Subsidies: Apply for fertilizer, seed, and equipment subsidies.\n"
     "- Crop Insurance: Apply and check claim status.\n"
     "- Fee: Free to nominal.\n"
     "- Processing Time: 5-7 working days.\n"
     "- Contact: agri-dept@state.gov.in")
]

# ---- Insert services into DB ----
cursor.executemany("INSERT OR IGNORE INTO services (service_id, title, details) VALUES (?, ?, ?)", services_data)

conn.commit()
conn.close()
print("SQLite database populated with all services successfully!")

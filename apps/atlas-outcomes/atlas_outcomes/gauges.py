"""The gauges: 60 USGS streamgages across 19 states and ~20 NWS offices.

Chosen for long daily-discharge records on rivers the NWS forecasts, with
upstream -> downstream pairs on the same river where one exists (the
upstream gauge's state at t is a feature of the downstream gauge's row).
Every site id's daily discharge was checked against the USGS site service on 2026-09-23; the
names, coordinates, county, HUC and drainage area come from that service at
harvest, not from this file.
"""

from __future__ import annotations

# site -> the upstream gauge on the same main stem (None when unpaired).
GAUGES: dict[str, str | None] = {
    # Potomac (LWX)
    "01610000": None,        # Potomac at Paw Paw, WV
    "01613000": "01610000",  # Potomac at Hancock, MD
    "01636500": None,        # Shenandoah at Millville, WV
    "01638500": "01613000",  # Potomac at Point of Rocks, MD
    "01643000": None,        # Monocacy at Jug Bridge, MD
    "01646500": "01638500",  # Potomac at Little Falls, DC
    "01668000": None,        # Rappahannock near Fredericksburg, VA
    # Susquehanna (BGM, CTP, LWX)
    "01531500": None,        # Towanda, PA
    "01536500": "01531500",  # Wilkes-Barre, PA
    "01570500": "01536500",  # Harrisburg, PA
    "01578310": "01570500",  # Conowingo, MD
    # Delaware / Schuylkill / Choptank (BGM, PHI)
    "01438500": None,        # Delaware at Montague, NJ
    "01446500": "01438500",  # Delaware at Belvidere, NJ
    "01463500": "01446500",  # Delaware at Trenton, NJ
    "01474500": None,        # Schuylkill at Philadelphia, PA
    "01491000": None,        # Choptank near Greensboro, MD
    # New England (BOX, BTV)
    "01100000": None,        # Merrimack at Lowell, MA
    "01184000": None,        # Connecticut at Thompsonville, CT
    "04290500": None,        # Winooski near Essex Junction, VT
    # Carolinas / Georgia (RAH, MHX, ILM, FFC)
    "02087500": None,        # Neuse near Clayton, NC
    "02089500": "02087500",  # Neuse at Kinston, NC
    "02102500": None,        # Cape Fear at Lillington, NC
    "02105769": "02102500",  # Cape Fear at Lock 1, NC
    "02336000": None,        # Chattahoochee at Atlanta, GA
    # Ohio River and tributaries (PBZ, ILN, LMK, PAH)
    "03049500": None,        # Allegheny at Natrona, PA
    "03085000": None,        # Monongahela at Braddock, PA
    "03086000": "03049500",  # Ohio at Sewickley, PA
    "03150000": None,        # Muskingum at McConnelsville, OH
    "03234000": None,        # Paint Creek near Bourneville, OH
    "03234500": None,        # Scioto at Higby, OH
    "03274000": None,        # Great Miami at Hamilton, OH
    # Ohio at Cincinnati (03255000) publishes stage only; Markland Dam is the next discharge gauge up.
    "03277200": None,        # Ohio at Markland Dam near Warsaw, KY
    "03294500": "03277200",  # Ohio at Louisville, KY
    "03303280": "03294500",  # Ohio at Cannelton, IN
    "03611500": "03303280",  # Ohio at Metropolis, IL
    # Upper Mississippi, Iowa, Illinois, Missouri (DVN, LSX, EAX)
    "05420500": None,        # Mississippi at Clinton, IA
    "05474500": "05420500",  # Mississippi at Keokuk, IA
    "07010000": "05474500",  # Mississippi at St. Louis, MO
    "07022000": "07010000",  # Mississippi at Thebes, IL
    "05446500": None,        # Rock River near Joslin, IL
    "05464500": None,        # Cedar at Cedar Rapids, IA
    "05465500": "05464500",  # Iowa River at Wapello, IA (below the Cedar confluence)
    "05586100": None,        # Illinois at Valley City, IL
    "06893000": None,        # Missouri at Kansas City, MO
    "06934500": "06893000",  # Missouri at Hermann, MO
    # Texas (FWD, HGX, EWX)
    "08057000": None,        # Trinity at Dallas
    "08066500": "08057000",  # Trinity at Romayor
    "08114000": None,        # Brazos at Richmond
    "08116650": "08114000",  # Brazos near Rosharon
    "08158000": None,        # Colorado at Austin
    "08167500": None,        # Guadalupe near Spring Branch
    "08176500": "08167500",  # Guadalupe at Victoria
    "08178000": None,        # San Antonio River at San Antonio
    # Pacific coast (MTR, SEW)
    "11463500": None,        # Russian River at Geyserville, CA
    "11467000": "11463500",  # Russian River at Hacienda Bridge, CA
    "12027500": None,        # Chehalis near Grand Mound, WA
    "12144500": None,        # Snoqualmie near Snoqualmie, WA
    "12150800": "12144500",  # Snohomish near Monroe, WA
    "12194000": None,        # Skagit near Concrete, WA
    "12200500": "12194000",  # Skagit near Mount Vernon, WA
}

# The site service's county, where the NWS county UGC differs. Connecticut
# replaced its counties with planning regions in 2022 (FIPS 09110 = Capitol);
# NWS county UGCs still name the legacy counties (Enfield is in Hartford, CTC003).
COUNTY_UGC_OVERRIDE = {"01184000": "CTC003"}

STATE_USPS = {
    "06": "CA", "09": "CT", "13": "GA", "17": "IL", "18": "IN", "19": "IA", "21": "KY",
    "24": "MD", "25": "MA", "29": "MO", "34": "NJ", "37": "NC", "39": "OH", "42": "PA",
    "48": "TX", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
}

# Local standard time offset (hours behind UTC) by the site service's tz_cd.
TZ_HOURS = {"EST": 5, "CST": 6, "MST": 7, "PST": 8}

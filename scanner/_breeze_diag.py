"""Find correct Breeze stock code for POLYCAB by trying variations."""
import os
from dotenv import load_dotenv
from breeze_connect import BreezeConnect

load_dotenv()

breeze = BreezeConnect(api_key=os.getenv("BREEZE_API_KEY"))
breeze.generate_session(
    api_secret=os.getenv("BREEZE_API_SECRET"),
    session_token=os.getenv("BREEZE_SESSION_TOKEN")
)

# Try different code variations for POLYCAB
candidates = ["POLCAB", "POLYCAB", "POLYCABL", "PLYCAB", "POLCABL"]

for code in candidates:
    r = breeze.get_quotes(
        stock_code=code, exchange_code="NSE",
        expiry_date="", product_type="cash", right="", strike_price=""
    )
    status = r.get("Status")
    error  = r.get("Error", "")
    succ   = r.get("Success")
    if status == 200 and succ:
        print(f"FOUND: stock_code='{code}'  ->  {succ}")
    else:
        print(f"  MISS: '{code}'  -> {error}")

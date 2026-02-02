"""Check what sheet tabs exist in the spreadsheet."""
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Authenticate
credentials = Credentials.from_service_account_file(
    'C:/Trading/canslim_monitor/google_credentials.json',
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)

service = build('sheets', 'v4', credentials=credentials)

# Get spreadsheet metadata
spreadsheet_id = '1yLPaurt3SLPOE84lz74bcLs5T_EiPpMqdvHICk5PLU'

try:
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

    print(f"Spreadsheet: {spreadsheet.get('properties', {}).get('title', 'Unknown')}")
    print("\nSheet tabs found:")

    for sheet in spreadsheet.get('sheets', []):
        props = sheet.get('properties', {})
        print(f"  - '{props.get('title')}' (ID: {props.get('sheetId')})")

except Exception as e:
    print(f"Error: {e}")

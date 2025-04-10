import requests
from datetime import datetime, timedelta
import argparse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

#Parsing arguments
parser = argparse.ArgumentParser(description="Skript k notikaci o platbe zavodu.")
parser.add_argument('--date-delta', type=int, required=True, help='Kolik dni dopredu se divame na zavody k platbe')
parser.add_argument('--level', type=str, required=True, help='Uroven zavodu k procesovani dle oris API - seznam oddeleny carkou, napr: "1,2,3,7,8,9"')
parser.add_argument('--discord-webhook', type=str,  help='Kompletni discord webhook URL')
parser.add_argument('--email-recipients', type=lambda s: [email.strip() for email in s.split(',')], help='Carkou oddeleny list mailu (napr.: a@x.com,b@y.com)')

args = parser.parse_args()
DISCORD_WEBHOOK_URL = args.discord_webhook
DATE_DELTA = args.date_delta
RECIPIENTS = args.email_recipients
LEVEL = args.level

#Default setup
ORIS_API_URL = "https://oris.orientacnisporty.cz/API/"
CLUB_ID = "205"  # SK Brno Žabovřesky

# Testing override
#LEVEL = "4"
#DATE_DELTA = 7
#DISCORD_WEBHOOK_URL = ""  # Replace with your actual webhook

#Get 
def get_unpaid_summary_for_club():
    """Fetch unpaid race fees and summarize for club 205."""
    now = datetime.now()
    future = now + timedelta(days=DATE_DELTA)
    date_to =  future.strftime("%Y-%m-%d")
    date_from = now.strftime("%Y-%m-%d")

    response = requests.get(ORIS_API_URL, params={"format": "json", "method": "getEventList", "myClubId": CLUB_ID, "datefrom": date_from, "dateto": date_to, "level": LEVEL, "sport":"1"})
    events = response.json()["Data"]  # Extract event details
    summary = []
    
    if not events:  # If empty list
      print("⚠️ No upcoming events found")
      return None

    for event in events.values():
        balance = get_balance_for_club(event)
        if balance:
            summary.append(balance)

    if not summary:
        return None
    return summary

def get_balance_for_club(event):
    balance_response = requests.get(ORIS_API_URL, params={
        "format": "json",
        "method": "getEventBalance",
        "eventid": event.get("ID"),
    })  
    account_details = requests.get(ORIS_API_URL, params={
        "format": "json",
        "method": "getEvent",
        "id": event.get("ID"),
    })
    # Get the JSON response data
    balance_data = balance_response.json()
    account_data = account_details.json()
    
    #Fail in case of issue with oris data
    if "Data" not in balance_data:
        print("❌ Error: No valid balance data received from ORIS API")
        return None
    
    #Do not process race with combined accounting
    if balance_data["Data"].get("EventID")!= event.get("ID"):
      print("❌ Event IDs do not match!")
      return None
    
    clubs_data = balance_data["Data"].get("Clubs", {})
    if isinstance(clubs_data, list):  # If it's an empty list, return None
        return None

    club_data = clubs_data.get(f"Club_{CLUB_ID}")

    #If there is nothing to process return
    if not club_data:
        return None
  
    return {
        "Race_name": event.get("Name"),
        "Race_id": event.get("ID"),
        "FeeTotal": club_data.get("FeeTotal", 0),
        "Paid": club_data.get("Paid", 0),
        "ToBePaid": club_data.get("ToBePaid", 0),
        "BankAccount": account_data["Data"].get("EntryBankAccount", "Bank account not found"),
        "VariableSymbol": club_data.get("PaymentVS", 0),
        "RaceDetails": f"https://oris.orientacnisporty.cz/PrehledVkladu?id={event.get('ID')}",
        "OrganiserName": account_data["Data"]['Org1'].get('Name',0),
        "OrganiserAbbr": account_data["Data"]['Org1'].get('Abbr',0)
    }

def prepare_message_discord(races):
    message = "# Co je potřeba zaplatit \n\n"

    for race in races:
      message += (
        f"**{race['Race_name']} (ID: {race['Race_id']})**\n"
        f"Organizátor: {race['OrganiserName']}\n"
        f"Celkový poplatek: {race['FeeTotal']} CZK\n"
        f"Zaplaceno: {race['Paid']} CZK\n"
        f"Zaplatit: **{race['ToBePaid']}** CZK\n"
        f"Bankovní účet: ({race['BankAccount']})\n"
        f"Variabilní symbol: {race['VariableSymbol']}\n"
        f"Detaily platby: [Klikněte zde]({race['RaceDetails']})\n"
        f"--------------------------------------\n"
      )
      send_to_discord(message)
      message = ""

def send_to_discord(mess):

# Sending the message to Discord
  payload = {
    "content": mess,
    "embeds": []
     }
  headers = {"Content-Type": "application/json"}
  response = requests.post(DISCORD_WEBHOOK_URL, json=payload, headers=headers)

# Print the response
  if response.status_code == 204:
    print(datetime.now().strftime("%Y-%m-%d"),": Message sent successfully!")
  else:
    print(datetime.now().strftime("%Y-%m-%d"),f": Failed to send message. Error: {response.status_code} - {response.text}")

def prepare_email_message(races):
    message = "Přehled pro platby závodů - Pozor, může zahrnovat celý víkend\n\n"

    for race in races:
        message += (
            f"{race['Race_name']} (ID: {race['Race_id']})\n"
            f"Organizátor: {race['OrganiserAbbr']}, {race['OrganiserName']}\n"
            f"--------------------------------------\n"
            f"Celkový poplatek: {race['FeeTotal']} CZK\n"
            f"Zaplaceno: {race['Paid']} CZK\n"
            f"Zaplatit: {race['ToBePaid']} CZK\n\n"
            f"Bankovní účet: {race['BankAccount']}\n"
            f"Variabilní symbol: {race['VariableSymbol']}\n"
            f"Detaily platby: {race['RaceDetails']}\n"
            f"======================================\n\n"
        )

    return message

def send_email(subject, body, to_email):
    """Send an email with the provided subject, body, and recipient."""
    from_email = "jan_zhanal@centrum.cz"  # Replace with your email
    from_password = "31windows"  # Replace with your email password or app password
    
    # Set up the MIME
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = ', '.join(to_email)
    msg['Subject'] = subject
    
    # Add body content to the email
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        # Set up the SMTP server (using Gmail in this example)
        server = smtplib.SMTP('smtp.centrum.cz', 587)  # Use the correct SMTP server for your email provider
        server.starttls()  # Secure the connection
        server.login(from_email, from_password)
        
        # Send the email
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        
        # Close the server
        server.quit()
        
        print(datetime.now().strftime("%Y-%m-%d"),": Email sent successfully!")
    except Exception as e:
        print(datetime.now().strftime("%Y-%m-%d"), f": Failed to send email. Error: {e}")


summ = get_unpaid_summary_for_club()
if DISCORD_WEBHOOK_URL:
  if summ:
    zprava = prepare_message_discord(summ)
  else:
    zprava = "No unpaid races found for the upcoming period."
    send_to_discord(zprava)
elif RECIPIENTS:
  if summ:
     send_email("Informace k platbě závodů OB:",prepare_email_message(summ),RECIPIENTS)
  else:
     print("Please specify email recipients of Discord webhook")
     exit(0)



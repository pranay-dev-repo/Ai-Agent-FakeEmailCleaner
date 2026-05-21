import os
import time
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DOMAINS_TO_TRASH = [
    "host.discountwalas.com", "indiamailers.com", "mailer.emailsinbox.com",
    "em.flickonclick.com", "mailer.officenewz.com", "em.smctradeonline.com",
    "rathi.com", "mail.beehiiv.com", "campaign1.nipponindia.email",
    "enews.sodapdf.com", "em.goconnectmail.com", "pnm.nobroker.in",
    "berribot.com", "wayfarertrip.com", "smt.plusoasis.com",
    "am.dealsboat.com", "springhr.com", "uplers.network",
    "consultbae.com", "zintro.com", "hiregenics.com",
    "ripplehire.com", "everexpanse.com", "nl.flickonclick.com",
    "mailer.moneycontrol.com", "blackwhite.in", "ansplacements.com",
    "finoux.com", "conceptshr.net", "teksystems.com",
    "spruceinfotech.com", "mg.sg.graphy.com", "cameoindia.com",
    "skillkart.co", "elearnmarkets.com", "varite.com",
    "tanishasystems.com", "protalentconnect.in", "tekishub.com",
    "mailer.eurekaforbeslimited.co.in", "faxoc.com", "mitsit.net",
    "primesoft.net", "centuryiq.in", "pmam.com",
    "digitalinclined.net", "talenttitanletters.com", "globeclients.com",
    "forward.net.in", "valuelabs.com", "therecruitx.com",
    "initialinfinity.com", "anandjikalyanjipedhi.org", "hirepro.in",
    "jmproapp.com", "rarefindindia.com", "notification.circle.so",
    "datasciencemasterminds.com", "dare2compete.news", "sysaccord.com",
    "cielhr.com", "nodnetworks.com", "photokhazana.com",
    "axelia.in", "msrtcors.com", "cvlindia.in",
    "innovasolutions.com", "ibridgetechsoft.com", "ktekresourcing.com",
    "people-prime.com", "globalhunt.in", "techslash.com",
    "applycup.com", "navasoftware.com", "noveltalentsolutions.com",
    "myanatomy.in", "mindpooltech.in", "infinitygrowth.live",
    "monocept.com", "saivasystem.com", "eteaminc.com",
    "winsoftech.com", "weareams.com", "konnectinsights.com",
    "codersbrain.com", "beacontrustee.co.in", "mybrandbook.co.in",
    "vp.pl", "etaashconsultants.com", "allegisglobalsolutions.com",
    "kasmodigital.com", "altezzasys.com", "kennit.co.in",
    "rightbrain.co.in", "orchasp.com", "pegasusinfocorp.com",
    "hnssolution.in", "hcapital.in", "sgsconsulting.com",
    "survik.com", "techopp.in", "techopportunity.in", "uto.in",
    "avihr.in",
    "beanhr.com",
    "careerguideline.net",
    "careervisions.org",
    "cpcareers.com",
    "daksyam.com",
    "email.citiustech.com",
    "email.microsoft.com",
    "email2.microsoft.com",
    "emaila.1mg.com",
    "emailer.idfcfirst.bank.in",
    "emailer.idfcfirstbank.com",
    "emailer.pharmeasy.in",
    "emailers.idfcfirst.bank.in",
    "emailers.idfcfirstbank.com",
    "empowerhr.in",
    "enrichtalents.com",
    "factorialsolutions.com",
    "flocareer.com",
    "googlemail.com",
    "headhuntershr.com",
    "impeccablehr.com",

    "jobs.shine.com",
    "jobsalert.shine.com",
    "jobsearch.shine.com",
    "jobseekers.shine.com",
    "litsaservices.com",
    "mail.instagram.com",
    "mailer.jio.com",
    "mnrsolutions.in",
    "mounttalent.com",
    "newsletters.analyticsvidhya.com",
    "nmplacement.com",
    "notifications-economictimes.com",
    "prismhrc.in",
    "rsquare-solutions.com",
    "samhrpo.com",
    "sensehr.com",
    "simplilearnmailer.com",
    "talent500.co",
    "talenti.biz",
    "timesjobs.com",
    "aegisconsultants.in",
    "enigmajobs.com",
    "hiring.shine.com",
    "atidan.com",
    "eclerx.com",
    "etprime.com",
    "excelityglobal.com",
    "glassdoor.com",
    "hirist.tech",
    "jmfl.com",
    "neoquant.com",
    "neweraindia.com",
    "northgateps.com",
    "scaler.com",
    "simplilearn.net",
    "stockedge.com",
    "stratosphere.co.in",
    "tgt.net.in",
    "ui.dev",
    "upskill.mygreatlearning.com",
    "upwork.com",
    "cred.club",
    "crio.co.in",
    "crio.in",
    "indeed.com",
    "integratedregistry.in",
    "mail.perplexity.ai",
    "mkttech.in",
    "money.livemint.com",
    "olaelectric.com",
    "quant.in",
    "tdsmail.taxosmart.in",
]

creds = Credentials(
    token=None,
    refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
    token_uri='https://oauth2.googleapis.com/token',
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    scopes=['https://www.googleapis.com/auth/gmail.modify'],
)
creds.refresh(Request())
service = build('gmail', 'v1', credentials=creds)

total_trashed = 0

for domain in DOMAINS_TO_TRASH:
    msg_ids = []
    page_token = None
    while True:
        kwargs = {'userId': 'me', 'q': f'in:inbox from:@{domain}', 'maxResults': 500}
        if page_token:
            kwargs['pageToken'] = page_token
        result = service.users().messages().list(**kwargs).execute()
        msg_ids.extend([m['id'] for m in result.get('messages', [])])
        page_token = result.get('nextPageToken')
        if not page_token:
            break

    if not msg_ids:
        continue

    # Batch trash in groups of 100
    for i in range(0, len(msg_ids), 100):
        batch = service.new_batch_http_request()
        for msg_id in msg_ids[i:i+100]:
            batch.add(service.users().messages().trash(userId='me', id=msg_id))
        try:
            batch.execute()
        except HttpError as e:
            print(f'  Batch error for {domain}: {e}', flush=True)
            time.sleep(2)

    total_trashed += len(msg_ids)
    print(f'[TRASHED {len(msg_ids):4d}] {domain}', flush=True)

print(f'\nDone. Total trashed: {total_trashed}', flush=True)

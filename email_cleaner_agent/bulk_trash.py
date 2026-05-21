import os
import time
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DOMAINS_TO_TRASH = [
    "aegisconsultants.in",
    "allegisglobalsolutions.com",
    "altezzasys.com",
    "am.dealsboat.com",
    "anandjikalyanjipedhi.org",
    "ansplacements.com",
    "applycup.com",
    "avihr.in",
    "axelia.in",
    "beacontrustee.co.in",
    "beanhr.com",
    "berribot.com",
    "blackwhite.in",
    "cameoindia.com",
    "campaign1.nipponindia.email",
    "careerguideline.net",
    "careervisions.org",
    "centuryiq.in",
    "cielhr.com",
    "codersbrain.com",
    "conceptshr.net",
    "consultbae.com",
    "cpcareers.com",
    "cred.club",
    "crio.co.in",
    "crio.in",
    "cvlindia.in",
    "daksyam.com",
    "dare2compete.news",
    "datasciencemasterminds.com",
    "digitalinclined.net",
    "eclerx.com",
    "elearnmarkets.com",
    "em.flickonclick.com",
    "em.goconnectmail.com",
    "em.smctradeonline.com",
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
    "enews.sodapdf.com",
    "enigmajobs.com",
    "enrichtalents.com",
    "etaashconsultants.com",
    "eteaminc.com",
    "etprime.com",
    "everexpanse.com",
    "excelityglobal.com",
    "factorialsolutions.com",
    "faxoc.com",
    "finoux.com",
    "flocareer.com",
    "forward.net.in",
    "glassdoor.com",
    "globalhunt.in",
    "globeclients.com",
    "googlemail.com",
    "hcapital.in",
    "headhuntershr.com",
    "hiregenics.com",
    "hirepro.in",
    "hiring.shine.com",
    "hirist.tech",
    "hnssolution.in",
    "host.discountwalas.com",
    "ibridgetechsoft.com",
    "impeccablehr.com",
    "indeed.com",
    "indiamailers.com",
    "infinitygrowth.live",
    "initialinfinity.com",
    "innovasolutions.com",
    "integratedregistry.in",
    "jmproapp.com",
    "jobs.shine.com",
    "jobsalert.shine.com",
    "jobsearch.shine.com",
    "jobseekers.shine.com",
    "kasmodigital.com",
    "kennit.co.in",
    "konnectinsights.com",
    "ktekresourcing.com",
    "litsaservices.com",
    "mail.beehiiv.com",
    "mail.instagram.com",
    "mail.perplexity.ai",
    "mailer.emailsinbox.com",
    "mailer.eurekaforbeslimited.co.in",
    "mailer.jio.com",
    "mailer.moneycontrol.com",
    "mailer.officenewz.com",
    "mg.sg.graphy.com",
    "mindpooltech.in",
    "mitsit.net",
    "mkttech.in",
    "mnrsolutions.in",
    "money.livemint.com",
    "monocept.com",
    "mounttalent.com",
    "msrtcors.com",
    "myanatomy.in",
    "mybrandbook.co.in",
    "navasoftware.com",
    "neoquant.com",
    "neweraindia.com",
    "newsletters.analyticsvidhya.com",
    "nl.flickonclick.com",
    "nmplacement.com",
    "nodnetworks.com",
    "northgateps.com",
    "notification.circle.so",
    "notifications-economictimes.com",
    "noveltalentsolutions.com",
    "olaelectric.com",
    "orchasp.com",
    "pegasusinfocorp.com",
    "people-prime.com",
    "photokhazana.com",
    "pmam.com",
    "pnm.nobroker.in",
    "primesoft.net",
    "prismhrc.in",
    "protalentconnect.in",
    "quant.in",
    "rarefindindia.com",
    "rathi.com",
    "rightbrain.co.in",
    "ripplehire.com",
    "rsquare-solutions.com",
    "saivasystem.com",
    "samhrpo.com",
    "scaler.com",
    "sensehr.com",
    "sgsconsulting.com",
    "simplilearn.net",
    "simplilearnmailer.com",
    "skillkart.co",
    "smt.plusoasis.com",
    "springhr.com",
    "spruceinfotech.com",
    "stratosphere.co.in",
    "survik.com",
    "sysaccord.com",
    "talent500.co",
    "talenti.biz",
    "talenttitanletters.com",
    "tanishasystems.com",
    "tdsmail.taxosmart.in",
    "techopp.in",
    "techopportunity.in",
    "techslash.com",
    "tekishub.com",
    "teksystems.com",
    "tgt.net.in",
    "therecruitx.com",
    "timesjobs.com",
    "ui.dev",
    "uplers.network",
    "uto.in",
    "valuelabs.com",
    "varite.com",
    "vp.pl",
    "wayfarertrip.com",
    "weareams.com",
    "winsoftech.com",
    "zintro.com",
    "choicetechlab.com",
    "mail.tatamf.in",
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

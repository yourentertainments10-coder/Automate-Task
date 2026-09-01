"""Load STARTER process drafts, one per job the team actually does.

These are drafts, not gospel. They were written from the real task history in
this system (Tally/Odoo reconciliation, dealer-portal MRP, collection visits,
dispatch runs...) but nobody outside the team can know the exact internal
steps -- which ledger, whose approval, which folder. Anything that needs a
person to confirm is marked [CONFIRM] in the text.

    python manage.py seed_sops --dry-run
    python manage.py seed_sops

Re-running is safe: a process whose title+version already exists is skipped,
never overwritten, so edits made in the app survive.
"""
from django.core.management.base import BaseCommand

from mistakes.models import SOP

DRAFTS = [
    # ----------------------------------------------------------------- accounts
    {
        "title": "Ledger reconciliation between Tally and Odoo",
        "department": "accounts",
        "category": "Reconciliation",
        "steps": [
            "Open the party ledger in Tally and the same party in Odoo for the chosen period",
            "Match the opening balance in both systems before looking at any entry",
            "Go entry by entry in date order and tick off the ones that match on date AND amount",
            "List every unmatched entry with its date, amount and which system it is missing from",
            "Fix the side that is wrong -- never edit both sides to meet in the middle",
            "Re-run the comparison until the closing balance matches in both systems",
            "Record the closing balance and the date you reconciled up to in the task",
        ],
        "checks": [
            "Closing balance is identical in Tally and Odoo to the paisa",
            "Every entry you changed has a note saying why it was changed",
            "[CONFIRM] Any difference above the agreed limit was shown to the Accounts Manager",
        ],
        "errors": [
            "Matching on amount alone, so two same-value entries on different dates get ticked",
            "Adjusting the balance with a manual entry instead of finding the real difference",
            "Reconciling only the current month while the difference started earlier",
            "Closing the task without writing down the balance that was agreed",
        ],
    },
    {
        "title": "Bank statement entry and bank reconciliation",
        "department": "accounts",
        "category": "Data Entry",
        "steps": [
            "Download the statement for the full period from the bank portal (no partial ranges)",
            "Check the account number on the statement against the ledger you are about to post to",
            "Enter each credit and debit with the bank's own date, not today's date",
            "Tag bank charges, interest and reversals to their own heads, not to a party ledger",
            "Reconcile the bank book against the statement closing balance",
            "Attach the statement PDF to the task",
        ],
        "checks": [
            "Statement closing balance equals the bank book closing balance",
            "No entry is dated outside the statement period",
            "Every charge line has a head -- none left in suspense",
        ],
        "errors": [
            "Posting to the wrong bank because two accounts have similar numbers",
            "Using the entry date instead of the value date on the statement",
            "Leaving bank charges unposted so the balance never matches",
        ],
    },
    {
        "title": "Purchase invoice entry for material received",
        "department": "accounts",
        "category": "Invoicing",
        "steps": [
            "Collect the supplier invoice and the warehouse receipt (GRN) for the same lot",
            "Check that the supplier name on the invoice matches the supplier master exactly",
            "Verify the GST number on the invoice against the supplier master",
            "Match every line item, quantity and rate against the purchase order",
            "Raise the difference with Purchase BEFORE entering, if quantity or rate differ",
            "Create the purchase voucher under the correct ledger and cost centre",
            "Attach the invoice copy to the task and file it in the month folder",
        ],
        "checks": [
            "Voucher total equals the invoice total to the paisa, including GST",
            "Quantity entered equals the quantity the warehouse actually received",
            "[CONFIRM] Invoices above the agreed value carry the manager's approval",
        ],
        "errors": [
            "Typing the part name instead of the part code",
            "Taking the rate from the quotation instead of the purchase order",
            "Entering the invoice before the material is physically received",
            "Missing the GST number, so input credit cannot be claimed later",
        ],
    },
    # -------------------------------------------------------------------- sales
    {
        "title": "Sales order punching and confirmation",
        "department": "sales",
        "category": "Data Entry",
        "steps": [
            "Take the order in writing (WhatsApp or email) -- never punch from a verbal order alone",
            "Check the customer's outstanding and credit limit before punching",
            "Punch each line with the part CODE, and confirm the rate against the current price list",
            "Confirm the order back to the customer with quantity, rate and expected date",
            "Send the confirmed order to the warehouse for picking",
            "Close the order in the system the same day it is punched",
        ],
        "checks": [
            "Every line has a part code, not just a description",
            "Rate matches the price list version in force today",
            "[CONFIRM] Orders beyond the credit limit were approved by the Sales Manager",
        ],
        "errors": [
            "Punching from memory after a phone call, with no written order",
            "Using an old price list after a rate revision",
            "Leaving orders unpunched at month end so they miss the month's numbers",
        ],
    },
    {
        "title": "Collection visit and clearing customer outstanding",
        "department": "sales",
        "category": "Collections",
        "steps": [
            "Print or open the customer's outstanding statement before leaving",
            "Agree the outstanding figure with the customer against their own ledger",
            "Collect the payment and issue a receipt on the spot",
            "Record the payment mode, instrument number and date in the task",
            "Photograph the cheque or payment proof and attach it to the task",
            "Hand the instrument to Accounts the same day, or deposit it and attach the slip",
            "Note the promised date in the task if the customer did not pay today",
        ],
        "checks": [
            "Receipt number recorded and proof attached",
            "Amount collected matches the amount entered in the system",
            "[CONFIRM] Cash above the agreed limit was deposited the same day",
        ],
        "errors": [
            "Visiting without the outstanding statement and arguing about the figure",
            "Holding a cheque for days before handing it to Accounts",
            "Closing the task without recording the next promised date",
        ],
    },
    {
        "title": "Price list and MRP setup in the dealer portal",
        "department": "sales",
        "category": "Data Entry",
        "steps": [
            "Get the approved price list from the brand or the manager, in writing",
            "Note the effective date -- do not load a rate before the date it applies from",
            "Enter the rates against the part CODE, brand by brand",
            "Cross-check a sample of at least ten parts against the source list",
            "Check the same parts in Odoo so the portal and Odoo agree",
            "Attach the approved price list to the task",
        ],
        "checks": [
            "Sample of ten parts matches the source list exactly",
            "MRP in the dealer portal equals the MRP in Odoo",
            "No rate is live before its effective date",
        ],
        "errors": [
            "Loading rates from a forwarded message instead of the approved list",
            "Updating the portal but not Odoo, so the two disagree and a credit note is needed",
            "Missing the effective date and billing at the new rate too early",
        ],
    },
    # ---------------------------------------------------------------- warehouse
    {
        "title": "Material receipt and GRN entry",
        "department": "warehouse",
        "category": "Invoicing",
        "steps": [
            "Check the vehicle number and the supplier name on the documents before unloading",
            "Count every box against the delivery challan before the driver leaves",
            "Open and check quantity inside the boxes for damage or shortage",
            "Photograph any damage or shortage immediately, with the challan visible",
            "Make the GRN entry the same day, against the correct purchase order",
            "Report any shortage to Purchase and Accounts the same day",
            "Put the material away in its allotted place, not on the floor",
        ],
        "checks": [
            "Box count on the GRN equals the physical count",
            "Damage photographs attached before the driver leaves",
            "Nothing left lying on the floor at the end of the shift",
        ],
        "errors": [
            "Signing the challan before counting",
            "Making the GRN the next day, so a shortage claim is too late",
            "Recording the ordered quantity instead of the received quantity",
        ],
    },
    {
        "title": "Dispatch run and delivery proof",
        "department": "warehouse",
        "category": "Dispatch Run",
        "steps": [
            "Pick against the picking list, part code by part code",
            "Get the picked lot checked by a second person before packing",
            "Pack and label each box with the customer name and invoice number",
            "Load and note the box count against the invoice",
            "Hand over and collect the receiver's signature or stamp on the copy",
            "Photograph the signed copy and attach it to the task the same day",
        ],
        "checks": [
            "Box count loaded equals the box count on the invoice",
            "Signed delivery proof attached before the task is completed",
        ],
        "errors": [
            "Dispatching without the second-person check",
            "Completing the task with no signed proof attached",
            "Sending the right part in the wrong quantity because only boxes were counted",
        ],
    },
    {
        "title": "Raising a credit note (CN) for an MRP or rate issue",
        "department": "warehouse",
        "category": "Data Entry",
        "steps": [
            "Establish the correct MRP from the approved price list, not from memory",
            "Compare it against the MRP that was actually billed",
            "Work out the difference per unit and the total for the billed quantity",
            "[CONFIRM] Get the credit note approved by the manager before raising it",
            "Raise the CN against the original invoice number, never as a standalone entry",
            "Attach the original invoice and the approved price list to the task",
            "Inform Accounts and the customer once the CN is issued",
        ],
        "checks": [
            "CN is linked to the original invoice number",
            "Difference amount recomputed and matches the CN value",
            "Approval recorded before the CN was raised",
        ],
        "errors": [
            "Raising the CN before fixing the MRP, so the next bill repeats the error",
            "Raising it against the wrong invoice",
            "Skipping the approval because the amount looked small",
        ],
    },
    # ------------------------------------------------------------------ support
    {
        "title": "Correcting master data in the dealer portal",
        "department": "support",
        "category": "Data Entry",
        "steps": [
            "Get the change request in writing, saying what is wrong and what it should be",
            "Note the current value before changing anything, in the task",
            "Make the change on ONE record first and verify it on screen",
            "Apply the change to the remaining records",
            "Check the same value in Odoo so the two systems agree",
            "Reply to the requester with what was changed and when",
        ],
        "checks": [
            "Old value recorded in the task before the change",
            "Portal and Odoo show the same value after the change",
            "Requester confirmed the change is what they asked for",
        ],
        "errors": [
            "Changing in bulk first and discovering the mapping was wrong",
            "Fixing the portal but leaving Odoo stale",
            "Acting on a verbal request with nothing in writing",
        ],
    },
    {
        "title": "Onboarding a new user in the internal apps",
        "department": "support",
        "category": "Data Entry",
        "steps": [
            "Get the joining details from HR: full name, department, role, mobile, email",
            "Create the user with the correct role -- role decides what they can see",
            "Set the reporting manager, or approvals will go to the admins instead",
            "Fill the email and WhatsApp number, or notifications will never reach them",
            "Share the login and make them change the password on first sign-in",
            "Walk them through their own screens once, and note it in the task",
        ],
        "checks": [
            "Reporting manager, email and mobile are all filled",
            "The person signed in successfully at least once",
            "Role matches what HR asked for -- not a guess",
        ],
        "errors": [
            "Typing the username wrong, so every later record points at the wrong person",
            "Leaving the reporting manager blank",
            "Giving a wider role than asked because it was quicker",
        ],
    },
]


class Command(BaseCommand):
    help = "Load starter SOP drafts for each department (safe to re-run)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        made = skipped = 0
        for d in DRAFTS:
            if SOP.objects.filter(title=d["title"], version="v1").exists():
                skipped += 1
                self.stdout.write(f"  exists, left alone: {d['title']}")
                continue
            self.stdout.write(self.style.SUCCESS(
                f"  {'would add' if dry else 'added'}: {d['title']}"))
            if not dry:
                SOP.objects.create(
                    title=d["title"], department=d["department"],
                    category=d["category"], version="v1",
                    steps="\n".join(d["steps"]),
                    checks="\n".join(d["checks"]),
                    common_errors="\n".join(d["errors"]),
                )
            made += 1
        self.stdout.write(self.style.SUCCESS(
            f"\n{made} draft(s) {'to add' if dry else 'added'} · {skipped} already there"))
        self.stdout.write(
            "\nThese are DRAFTS written from your task history. Every department "
            "head should read theirs, fix what is wrong, and fill in anything "
            "marked [CONFIRM] before anyone is judged against it.")

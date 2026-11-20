#!/usr/bin/env python3
"""Step 3 of the main-sample counterfactual: field classes for the canonical forms.

Built from the API schemas only (data/api_docs/standard/*.json of both stands, write APIs
from write_apis.txt), BEFORE any matching is run. Output: reports/counterfactual_main/id_fields.json

Classes of a write-API parameter:
  auth      - removed in every form
  flag      - removed in lenient (a switch that does not change which object is written)
  target    - names the target object: *_id, e-mail addresses, phone numbers, file paths,
              plus explicit identifiers listed in TARGET_EXTRA
  amount    - quantities and sums
  other     - everything else (free text, address parts, dates, positions, ratings,
              booleans that are part of the written value). Dropped in the ids form.
ids form = target + amount fields only.
"""
import collections, json, pathlib

OUT = pathlib.Path("reports/counterfactual_main")
OUT.mkdir(parents=True, exist_ok=True)
STANDS = {"0.1.0": "replay_root", "0.2.0": "stand020"}
APPS = ("amazon", "file_system", "gmail", "phone", "simple_note", "splitwise", "spotify",
        "supervisor", "todoist", "venmo")

AUTH = {"access_token": "login token", "file_system_access_token": "file system login token",
        "password": "password"}
FLAGS = {
    "clear_cart_first": "from the pilot: clearing the cart before ordering, the object of the write (order) is the same",
    "clear_wish_list_first": "the same for the wish list",
    "overwrite": "permission to overwrite an existing file/object; the path (object) is given separately",
    "allow_if_exists": "permission for an already existing object; the object is given by the path",
    "retain_dates": "keep the dates of the source file when copying/moving; the object is the same",
    "track_browsing_history": "a write to the browsing history as side accounting; the object of the write is the same",
}
# booleans deliberately NOT treated as flags (they change what is written or which objects
# are affected): draft_not_send (draft vs sent e-mail), delete_directory,
# delete_compressed_file, recursive (which objects are deleted), and value booleans
# is_completed, read, pinned, enabled, private, is_public, is_favorite, is_archived, loop,
# vibration (the new value of the object).
NOT_FLAGS = {"draft_not_send": "a draft or a sent email are different objects",
             "delete_directory": "whether to delete the source folder — changes the set of affected objects",
             "delete_compressed_file": "whether to delete the archive — changes the set of affected objects",
             "recursive": "recursiveness — changes the set of affected objects",
             "is_completed": "new value of the object", "read": "new value of the object",
             "pinned": "new value of the object", "enabled": "new value of the object",
             "private": "new value of the object", "is_public": "new value of the object",
             "is_favorite": "new value of the object", "is_archived": "new value of the object",
             "loop": "new value of the object", "vibration": "new value of the object"}
AMOUNT = {"quantity", "amount", "paid_amount", "debt_amounts"}
EMAILS = {"email", "user_email", "receiver_email", "payer_email", "assignee_email",
          "email_addresses", "debtor_emails", "member_emails", "recipient_email_addresses"}
PATH_SUFFIX = ("file_path", "directory_path", "file_paths")
TARGET_EXTRA = {
    "phone_number": "phone",
    "card_number": "the card number names the card being added/changed",
    "promo_code": "the code names the promo object",
    "invitation_code": "the invitation code names the invitation object",
    "invite_code": "the invitation code names the invitation object",
    "attachment_file_name": "the attachment name names the target file (saving the attachment)",
}


def cls(name, typ):
    if name in AUTH:
        return "auth"
    if name in FLAGS:
        return "flag"
    if name in AMOUNT:
        return "amount"
    if name.endswith("_id") or name in EMAILS or name.endswith(PATH_SUFFIX) or name in TARGET_EXTRA:
        return "target"
    return "other"


def main():
    writes = set(open("write_apis.txt").read().split())
    per_api, names = {}, collections.defaultdict(lambda: dict(types=set(), apis=set()))
    for dv, st in STANDS.items():
        for app in APPS:
            p = pathlib.Path(st) / "data" / "api_docs" / "standard" / f"{app}.json"
            if not p.exists():
                continue
            for n, a in json.load(open(p)).items():
                k = f"{app}.{n}"
                if k not in writes:
                    continue
                ent = per_api.setdefault(k, {})
                for prm in a["parameters"]:
                    ent[prm["name"]] = cls(prm["name"], prm["type"])
                    names[prm["name"]]["types"].add(prm["type"])
                    names[prm["name"]]["apis"].add(k)
    out = dict(
        built_from="data/api_docs/standard/*.json (0.1.0: replay_root, 0.2.0: stand020) ∩ write_apis.txt",
        rule=__doc__.split("Classes of a write-API parameter:")[1].strip(),
        auth=AUTH, lenient_flags=FLAGS, booleans_not_flags=NOT_FLAGS,
        amount=sorted(AMOUNT), target_emails=sorted(EMAILS), target_path_suffixes=list(PATH_SUFFIX),
        target_extra=TARGET_EXTRA,
        params={n: dict(class_=cls(n, None), types=sorted(v["types"]), n_apis=len(v["apis"]))
                for n, v in sorted(names.items())},
        per_api={k: dict(sorted(v.items())) for k, v in sorted(per_api.items())},
    )
    json.dump(out, open(OUT / "id_fields.json", "w"), ensure_ascii=False, indent=1, sort_keys=False)
    c = collections.Counter(v["class_"] for v in out["params"].values())
    print(f"write APIs {len(per_api)}, parameters {len(names)}: {dict(c)}")
    for k in ("target", "amount", "flag", "auth"):
        print(k, ":", ", ".join(n for n, v in out["params"].items() if v["class_"] == k))


if __name__ == "__main__":
    main()

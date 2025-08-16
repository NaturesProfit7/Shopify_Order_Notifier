from services.phone_utils import normalize_ua_phone, pretty_ua_phone
from services.vcf_service import build_contact_vcf

p = normalize_ua_phone("+380 (67) 232 62 39")  # -> "+380672326239"
print("pretty:", pretty_ua_phone(p))           # -> "+38•067•232•62•39"

vcf_bytes, fname = build_contact_vcf(
    first_name="Іван",
    last_name="Петренко",
    order_id="1694",
    phone_e164=p,
)
print(fname, vcf_bytes.decode("utf-8"))

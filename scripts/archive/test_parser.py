import re
pattern = r"(.+)\s\((.+)\)\s@\s₹(.+)"
text = 'Coconut (Nos) @ ₹80, Banana (Nendran / Robusta) (Dozen) @ ₹85, Betel Leaves (25 leaves bundle) @ ₹48, Arecanut (Adakka) (100 g) @ ₹35, Camphor (100 g) @ ₹85, Incense Sticks (Agarbathi) (Packet) @ ₹50, Payasam Rice (KG) @ ₹75'
new_items = {}
for part in text.split(','):
    match = re.search(pattern, part.strip())
    if match:
        name = match.group(1).strip()
        unit = match.group(2).strip()
        price = float(match.group(3).strip())
        new_items[name] = {"price": price, "unit": unit}
print('NEW_ITEMS:', new_items)

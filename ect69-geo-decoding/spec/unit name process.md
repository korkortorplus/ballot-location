# Unit Name Processing Spec

## Overview

Parse Thai voting station location strings (`สถานที่เลือกตั้งกลาง`) into structured components for geocoding.

## Output Schema

```yaml
parsed_location:
  raw: string                # original text
  location_name: string      # main venue name (for geocoding)
  location_type: enum?       # classified venue type
  area_prefix: string?       # บริเวณ, เต็นท์, ลานจอดรถ, etc.
  buildings: list[string]    # building names (supports multiple)
  floor: string?             # ชั้น 1, ชั้นล่าง, etc.
  extra_info: string?        # parenthetical details
  subdistrict: string?       # แขวง (BKK) / ตำบล (province)
  district: string?          # เขต (BKK) / อำเภอ (province)
  province: string?          # parsed if present
```

## Location Types (Enum)

| Type | Thai | Frequency |
|------|------|-----------|
| `assembly_hall` | หอประชุม | 45% |
| `school` | โรงเรียน | 24% |
| `government_office` | สำนักงาน, ที่ว่าการ | 7% |
| `temple` | วัด | 11% |
| `dome` | โดม | 9% |
| `university` | มหาวิทยาลัย | 3% |
| `mall` | ศูนย์การค้า | <1% |
| `sports_center` | ศูนย์กีฬา, โรงยิม | <1% |
| `other` | - | - |

## Area Prefixes

Extract and classify leading descriptors:

| Prefix | Meaning |
|--------|---------|
| `บริเวณ` | general area of |
| `เต็นท์บริเวณ` | tent area of |
| `อาคาร` | building |
| `ห้อง` | room |
| `ลานจอดรถ` | parking lot |
| `โดม` | dome/covered area |
| `ศาลา` | pavilion |
| `ลาน` | yard/plaza |

## Parsing Rules

### Rule 1: Administrative Suffix Extraction

Parse from end of string, looking for administrative markers:

**Bangkok format:**
```
... แขวง{subdistrict} เขต{district}
... แขวง{subdistrict}  # district may be omitted
```

**Provincial format:**
```
... ตำบล{subdistrict} อำเภอ{district}
... อำเภอ{district}   # often only amphoe is present
```

### Rule 2: Multiple Buildings

Split on conjunctions when multiple buildings listed:

- `และ` (and)
- `กับ` (with)
- `,` (comma)

```
อาคาร X และ อาคาร Y ศูนย์ Z
→ buildings: [อาคาร X, อาคาร Y]
→ location_name: ศูนย์ Z
```

### Rule 3: Parenthetical Information

Preserve but classify parenthetical content:

| Pattern | Type | Example |
|---------|------|---------|
| `(ฝั่ง...)` | direction | (ฝั่งธนบุรี) |
| `(ซอย...)` | soi reference | (ซอยแจ้งวัฒนะ 7) |
| `(ชั่วคราว)` | temporary | (ชั่วคราว) |
| `(alias)` | nickname | (ไทย-ญี่ปุ่น), (ตะวันนา 2) |

### Rule 4: Floor Extraction

```
ชั้น {N}     → floor: "ชั้น {N}"
ชั้นล่าง     → floor: "ชั้นล่าง"
```

---

## Examples

### Example 1: Simple Bangkok

**Input:**
```
บริเวณวิทยาลัยเทคนิคราชสิทธาราม แขวงบางบอนเหนือ เขตบางบอน
```

**Output:**
```yaml
raw: บริเวณวิทยาลัยเทคนิคราชสิทธาราม แขวงบางบอนเหนือ เขตบางบอน
location_name: วิทยาลัยเทคนิคราชสิทธาราม
location_type: school
area_prefix: บริเวณ
buildings: []
floor: null
extra_info: null
subdistrict: บางบอนเหนือ
district: บางบอน
province: null
```

### Example 2: With Parenthetical

**Input:**
```
เต็นท์บริเวณถนนทางเข้าศูนย์ราชการเฉลิมพระเกียรติฯ (ซอยแจ้งวัฒนะ 7) แขวงทุ่งสองห้อง เขตหลักสี่
```

**Output:**
```yaml
raw: เต็นท์บริเวณถนนทางเข้าศูนย์ราชการเฉลิมพระเกียรติฯ (ซอยแจ้งวัฒนะ 7) แขวงทุ่งสองห้อง เขตหลักสี่
location_name: ศูนย์ราชการเฉลิมพระเกียรติฯ
location_type: government_office
area_prefix: เต็นท์บริเวณถนนทางเข้า
buildings: []
floor: null
extra_info: ซอยแจ้งวัฒนะ 7
subdistrict: ทุ่งสองห้อง
district: หลักสี่
province: null
```

### Example 3: With Floor

**Input:**
```
บริเวณชั้น 1 อาคารนิมิบุตร แขวงวังใหม่
```

**Output:**
```yaml
raw: บริเวณชั้น 1 อาคารนิมิบุตร แขวงวังใหม่
location_name: อาคารนิมิบุตร
location_type: other
area_prefix: บริเวณ
buildings: [อาคารนิมิบุตร]
floor: ชั้น 1
extra_info: null
subdistrict: วังใหม่
district: null
province: null
```

### Example 4: Multiple Buildings

**Input:**
```
อาคารกีฬาเวสน์ 1 และ อาคารกีฬาเวสน์ 2 ศูนย์เยาวชนกรุงเทพมหานคร (ไทย-ญี่ปุ่น) ดินแดง แขวงดินแดง
```

**Output:**
```yaml
raw: อาคารกีฬาเวสน์ 1 และ อาคารกีฬาเวสน์ 2 ศูนย์เยาวชนกรุงเทพมหานคร (ไทย-ญี่ปุ่น) ดินแดง แขวงดินแดง
location_name: ศูนย์เยาวชนกรุงเทพมหานคร (ไทย-ญี่ปุ่น) ดินแดง
location_type: sports_center
area_prefix: null
buildings: [อาคารกีฬาเวสน์ 1, อาคารกีฬาเวสน์ 2]
floor: null
extra_info: ไทย-ญี่ปุ่น
subdistrict: ดินแดง
district: null
province: null
```

### Example 5: Provincial (Simple)

**Input:**
```
หอประชุมอำเภอท่าม่วง
```

**Output:**
```yaml
raw: หอประชุมอำเภอท่าม่วง
location_name: หอประชุมอำเภอท่าม่วง
location_type: assembly_hall
area_prefix: null
buildings: []
floor: null
extra_info: null
subdistrict: null
district: ท่าม่วง
province: null
```

### Example 6: Provincial with Amphoe in String

**Input:**
```
หอประชุมโรงเรียนคลองท่อมราษฎร์รังสรรค์ อำเภอคลองท่อม
```

**Output:**
```yaml
raw: หอประชุมโรงเรียนคลองท่อมราษฎร์รังสรรค์ อำเภอคลองท่อม
location_name: โรงเรียนคลองท่อมราษฎร์รังสรรค์
location_type: school
area_prefix: หอประชุม
buildings: []
floor: null
extra_info: null
subdistrict: null
district: คลองท่อม
province: null
```

### Example 7: Mall with Floor

**Input:**
```
ห้องพระราม 2 ฮอลล์ ชั้น 4 ศูนย์การค้าเซ็นทรัลพลาซา พระราม 2
```

**Output:**
```yaml
raw: ห้องพระราม 2 ฮอลล์ ชั้น 4 ศูนย์การค้าเซ็นทรัลพลาซา พระราม 2
location_name: ศูนย์การค้าเซ็นทรัลพลาซา พระราม 2
location_type: mall
area_prefix: ห้องพระราม 2 ฮอลล์
buildings: []
floor: ชั้น 4
extra_info: null
subdistrict: null
district: null
province: null
```

### Example 8: Parking Lot with Parenthetical

**Input:**
```
เต็นท์ลานจอดรถโลตัสพระราม 3 (ฝั่งถนนนราธิวาสราชนครินทร์) แขวงช่องนนทรี
```

**Output:**
```yaml
raw: เต็นท์ลานจอดรถโลตัสพระราม 3 (ฝั่งถนนนราธิวาสราชนครินทร์) แขวงช่องนนทรี
location_name: โลตัสพระราม 3
location_type: mall
area_prefix: เต็นท์ลานจอดรถ
buildings: []
floor: null
extra_info: ฝั่งถนนนราธิวาสราชนครินทร์
subdistrict: ช่องนนทรี
district: null
province: null
```

---

## Notes

1. **Geocoding priority**: Use `location_name` + `subdistrict` + `district` for best geocoding results
2. **CSV enrichment**: The input CSV already has `จังหวัด` (province) and `เขต` (district for Bangkok) columns - use these to validate/supplement parsed values
3. **Fallback**: If parsing fails, use the full raw string for geocoding

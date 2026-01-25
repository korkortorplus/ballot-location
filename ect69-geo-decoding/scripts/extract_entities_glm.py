#!/usr/bin/env python3
"""Extract entities from voting location strings using Ollama (GLM-4.7-flash)."""

import json
import subprocess
import pandas as pd
from pathlib import Path
from tqdm import tqdm

OLLAMA_HOST = "vedas"
MODEL = "glm-4.7-flash:latest"

SYSTEM_PROMPT = """คุณเป็นผู้เชี่ยวชาญในการแยกข้อมูลสถานที่ภาษาไทย กรุณาแยกข้อมูลจากชื่อสถานที่เลือกตั้งให้อยู่ในรูปแบบ JSON

## Output Schema
```json
{
  "location_name": "string - ชื่อสถานที่หลัก (สำหรับ geocoding)",
  "location_type": "enum - assembly_hall|school|government_office|temple|dome|university|mall|sports_center|other",
  "area_prefix": "string|null - บริเวณ, เต็นท์, ลานจอดรถ, etc.",
  "buildings": ["list - ชื่ออาคาร (รองรับหลายอาคาร)"],
  "floor": "string|null - ชั้น 1, ชั้นล่าง, etc.",
  "extra_info": "string|null - ข้อมูลในวงเล็บ",
  "subdistrict": "string|null - แขวง/ตำบล (ไม่รวมคำนำหน้า)",
  "district": "string|null - เขต/อำเภอ (ไม่รวมคำนำหน้า)"
}
```

## Location Types
- assembly_hall: หอประชุม
- school: โรงเรียน, วิทยาลัย
- government_office: สำนักงาน, ที่ว่าการ
- temple: วัด
- dome: โดม
- university: มหาวิทยาลัย
- mall: ศูนย์การค้า, โลตัส, บิ๊กซี
- sports_center: ศูนย์กีฬา, โรงยิม, สนามกีฬา
- other: อื่นๆ

## Examples

Input: บริเวณวิทยาลัยเทคนิคราชสิทธาราม แขวงบางบอนเหนือ เขตบางบอน
Output: {"location_name": "วิทยาลัยเทคนิคราชสิทธาราม", "location_type": "school", "area_prefix": "บริเวณ", "buildings": [], "floor": null, "extra_info": null, "subdistrict": "บางบอนเหนือ", "district": "บางบอน"}

Input: เต็นท์บริเวณถนนทางเข้าศูนย์ราชการเฉลิมพระเกียรติฯ (ซอยแจ้งวัฒนะ 7) แขวงทุ่งสองห้อง เขตหลักสี่
Output: {"location_name": "ศูนย์ราชการเฉลิมพระเกียรติฯ", "location_type": "government_office", "area_prefix": "เต็นท์บริเวณถนนทางเข้า", "buildings": [], "floor": null, "extra_info": "ซอยแจ้งวัฒนะ 7", "subdistrict": "ทุ่งสองห้อง", "district": "หลักสี่"}

Input: บริเวณชั้น 1 อาคารนิมิบุตร แขวงวังใหม่
Output: {"location_name": "อาคารนิมิบุตร", "location_type": "other", "area_prefix": "บริเวณ", "buildings": ["อาคารนิมิบุตร"], "floor": "ชั้น 1", "extra_info": null, "subdistrict": "วังใหม่", "district": null}

Input: อาคารกีฬาเวสน์ 1 และ อาคารกีฬาเวสน์ 2 ศูนย์เยาวชนกรุงเทพมหานคร (ไทย-ญี่ปุ่น) ดินแดง แขวงดินแดง
Output: {"location_name": "ศูนย์เยาวชนกรุงเทพมหานคร (ไทย-ญี่ปุ่น) ดินแดง", "location_type": "sports_center", "area_prefix": null, "buildings": ["อาคารกีฬาเวสน์ 1", "อาคารกีฬาเวสน์ 2"], "floor": null, "extra_info": "ไทย-ญี่ปุ่น", "subdistrict": "ดินแดง", "district": null}

Input: หอประชุมโรงเรียนคลองท่อมราษฎร์รังสรรค์ อำเภอคลองท่อม
Output: {"location_name": "โรงเรียนคลองท่อมราษฎร์รังสรรค์", "location_type": "school", "area_prefix": "หอประชุม", "buildings": [], "floor": null, "extra_info": null, "subdistrict": null, "district": "คลองท่อม"}

Input: เต็นท์ลานจอดรถโลตัสพระราม 3 (ฝั่งถนนนราธิวาสราชนครินทร์) แขวงช่องนนทรี
Output: {"location_name": "โลตัสพระราม 3", "location_type": "mall", "area_prefix": "เต็นท์ลานจอดรถ", "buildings": [], "floor": null, "extra_info": "ฝั่งถนนนราธิวาสราชนครินทร์", "subdistrict": "ช่องนนทรี", "district": null}

ตอบเป็น JSON เท่านั้น ไม่ต้องมีคำอธิบายเพิ่ม"""


def call_ollama(text: str) -> dict:
    """Call Ollama API via SSH to vedas."""
    prompt = f"แยกข้อมูลจากสถานที่นี้:\n{text}"

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
        "options": {"temperature": 0.1},
    }

    payload_json = json.dumps(payload, ensure_ascii=False)

    cmd = [
        "ssh",
        OLLAMA_HOST,
        f"curl -s http://localhost:11434/api/generate -d '{payload_json}'",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        return {"error": result.stderr}

    try:
        response = json.loads(result.stdout)
        answer = response.get("response", "")
        # Try to parse the JSON from the response
        start = answer.find("{")
        end = answer.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(answer[start:end])
        return {"error": "No JSON found", "raw": answer}
    except json.JSONDecodeError as e:
        return {"error": str(e), "raw": result.stdout}


def main():
    input_file = Path(
        "/home/ben/ddd/ninyawee/ballot-location/ect69-geo-decoding/inputs/vote69_early_voting_เลือกตั้งล่วงหน้า.csv"
    )
    output_file = input_file.parent / "vote69_early_voting_entities_glm.csv"

    df = pd.read_csv(input_file)
    locations = df["สถานที่เลือกตั้งกลาง"].tolist()

    results = []
    for loc in tqdm(locations, desc="Extracting entities (GLM)"):
        entity = call_ollama(loc)
        entity["original"] = loc
        results.append(entity)

    out_df = pd.DataFrame(results)
    out_df.to_csv(output_file, index=False)
    print(f"\nSaved to: {output_file}")
    print(f"Total: {len(results)} rows")


if __name__ == "__main__":
    main()

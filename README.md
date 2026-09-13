# 📊 XAUUSD SMC Signal Bot

บอทแจ้งสัญญาณ BUY/SELL ทองคำ (XAUUSD) ผ่าน Telegram  
ใช้ Smart Money Concepts: **CHoCH + Order Block + FVG + Supply/Demand Zone**

---

## 📋 สิ่งที่ต้องเตรียม

1. **MetaTrader 5** ติดตั้งและเปิดอยู่บน PC เครื่องนี้
2. **Python 3.10+** ติดตั้งแล้ว
3. **Telegram Bot** สร้างจาก @BotFather

---

## 🚀 วิธีติดตั้ง

### ขั้นตอนที่ 1: ติดตั้ง Python packages

เปิด Command Prompt หรือ PowerShell แล้วรัน:

```
cd C:\Users\cww11\Downloads\MT
pip install -r requirements.txt
```

### ขั้นตอนที่ 2: สร้าง Telegram Bot

1. เปิด Telegram → ค้นหา **@BotFather**
2. พิมพ์ `/newbot` → ตั้งชื่อบอท → จะได้ **Bot Token** (เช่น `123456:ABC-DEF...`)
3. เปิดบอทที่สร้าง แล้วกด **Start**
4. หา **Chat ID** ของตัวเอง:
   - ค้นหา **@userinfobot** ใน Telegram
   - กด Start → จะได้เลข Chat ID (เช่น `987654321`)

### ขั้นตอนที่ 3: ตั้งค่า .env

สร้างไฟล์ `.env` ในโฟลเดอร์ `MT`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=987654321
```

> ⚠️ ใส่ค่าจริงของตัวเอง ไม่ใช่ตัวอย่าง

### ขั้นตอนที่ 4: เปิด MetaTrader 5

- ต้องเปิด MT5 ค้างไว้ตลอดที่บอทรัน
- ต้องมีชาร์ต XAUUSD เปิดอยู่ (timeframe อะไรก็ได้)
- ใน MT5: **Tools → Options → Expert Advisors** → ✅ Allow algorithmic trading

---

## ▶️ วิธีรันบอท

```
cd C:\Users\cww11\Downloads\MT
python main.py
```

จะเห็น:

```
==================================================
  XAUUSD SMC Signal Bot
  H1 trend → M15 entry | RR 1:2.0
  Min confluence: 2/4
==================================================
[MT5] Connected — MetaTrader 5
[Main] Polling every 15s for new M15 candle ...
```

บอทจะ:
- ตรวจทุก 15 วินาทีว่าแท่ง M15 ใหม่ปิดหรือยัง
- ถ้าปิด → วิเคราะห์ H1 (ดูเทรนด์) + M15 (หาจุดเข้า)
- ถ้าเจอ confluence ≥ 2 → ส่ง Telegram ทันที

**หยุดบอท:** กด `Ctrl + C`

---

## ⚙️ ปรับค่าได้ใน config.py

| ค่า | Default | คำอธิบาย |
|---|---|---|
| `SYMBOL` | `XAUUSD` | คู่เงินที่จะวิเคราะห์ |
| `RR_RATIO` | `2.0` | Risk:Reward (1:2) |
| `MIN_CONFLUENCE` | `2` | จำนวน zone ขั้นต่ำที่ต้องซ้อนกัน |
| `SWING_LOOKBACK` | `3` | จำนวนแท่งซ้าย-ขวาสำหรับหา swing |
| `IMPULSE_THRESHOLD` | `1.5` | ตัวคูณ ATR สำหรับ impulsive move |
| `SL_BUFFER` | `0.5` | Buffer ใต้/เหนือ zone (5 pips) |
| `POLL_INTERVAL_SEC` | `15` | ตรวจแท่งใหม่ทุกกี่วินาที |

---

## 📁 โครงสร้างไฟล์

```
MT/
├── .env               ← Token + Chat ID (สร้างเอง)
├── .env.example       ← ตัวอย่าง
├── config.py          ← ค่าตั้งค่าทั้งหมด
├── mt5_data.py        ← ดึงข้อมูลจาก MT5
├── smc_core.py        ← Logic: CHoCH, OB, FVG, Supply/Demand
├── signal_engine.py   ← ประกอบสัญญาณ + คำนวณ SL/TP
├── telegram_bot.py    ← จัดข้อความ + ส่ง Telegram
├── main.py            ← จุดเริ่มต้น (รันไฟล์นี้)
└── requirements.txt   ← dependencies
```

---

## 📱 ตัวอย่างข้อความ Telegram

```
🟢 BUY SIGNAL — XAUUSD
━━━━━━━━━━━━━━━━━━━
📊 H1 Trend: BULLISH (CHoCH detected)
🎯 M15 Confluence: OB + FVG (2/4)

💰 Entry: 2,345.50
🛑 SL: 2,340.00 (-55 pips)
✅ TP: 2,356.50 (+110 pips)
📏 RR: 1:2.0

⏰ 2026-09-07 14:15 (M15 close)
━━━━━━━━━━━━━━━━━━━
⚠️ สัญญาณเท่านั้น ไม่ใช่คำแนะนำการลงทุน
```

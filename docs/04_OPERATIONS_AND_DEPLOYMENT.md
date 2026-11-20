# Operations, Deployment & Runbook

**Document Class:** Operations Guide & Standard Operating Procedures (SOP)  
**Target Audience:** DevOps / Infrastructure Engineers / Systems Administrators  
**Host Environment:** macOS / Linux (Ubuntu 22.04 LTS / Debian 12 recommended)  
**Python Runtime:** Python 3.10 – 3.14  

---

## 1. System Requirements & Dependencies

### Hardware Requirements
- **CPU:** 2 vCPU minimum (4 vCPU recommended)
- **RAM:** 2 GB minimum (4 GB recommended for concurrent PDF rendering)
- **Disk:** 10 GB SSD space (for logging, outputs, and attachments)
- **Network:** Outbound HTTPS (port 443 to `api.groq.com`), Outbound IMAP/SSL (port 993 to `mail.abdullah-traders.com.pk`)

### Software Stack
- Python 3.10+ with standard library (`imaplib`, `email`, `re`, `fcntl`)
- Pip packages: `streamlit`, `langgraph`, `langchain-groq`, `pydantic`, `reportlab`, `pandas`, `python-dotenv`, `pytest`

---

## 2. Initial Setup & Configuration Runbook

### Step 1: Clone Repository & Virtual Environment Setup
```bash
cd /opt/procurement-agent  # or ~/Desktop/PP/procurement-agent
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy the template and populate production credentials:
```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env`:
```env
# Groq Cloud API Configuration
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Identity & Company Details
SENDER_NAME=Abuzar Rashid
SENDER_COMPANY=Abdullah Traders
WEBMAIL_URL=https://rc.ds.network/

# IMAP Webmail Reply Monitoring (mail.abdullah-traders.com.pk)
IMAP_HOST=mail.abdullah-traders.com.pk
IMAP_PORT=993
IMAP_USE_SSL=true
IMAP_USER=sales@abdullah-traders.com.pk
IMAP_PASSWORD=your_mailbox_password_here
IMAP_MAILBOX=INBOX
IMAP_SCAN_LAST_N=50
```

### Step 3: Populate Private Business Data
```bash
cp data/suppliers.example.csv data/suppliers.csv
cp data/banned_terms.example.txt data/banned_terms.txt
cp data/company.example.json data/company.json
```
- In `data/suppliers.csv`: Add supplier contacts per brand (`brand,contact_name,email,company`).
- In `data/banned_terms.txt`: List all end-client corporate entities, power plant names, and project codes (one per line).
- In `data/company.json`: Verify NTN, STRN, address, phone numbers, and company accent hex colors.

---

## 3. Launching & Running Streamlit

### Local / Development Mode
```bash
make run
# Or directly:
.venv/bin/streamlit run app.py
```

### Production Headless Server (systemd or daemon)
To run permanently on port 8501 without opening browser windows:
```bash
.venv/bin/streamlit run app.py \
  --server.port 8501 \
  --server.headless true \
  --server.address 0.0.0.0 \
  --browser.gatherUsageStats false
```

### Reverse Proxy Configuration (Nginx snippet)
If exposing via HTTPS on a corporate domain:
```nginx
server {
    listen 443 ssl http2;
    server_name procurement.abdullah-traders.com.pk;

    ssl_certificate /etc/letsencrypt/live/procurement/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/procurement/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

---

## 4. Operational Monitoring & Health Checks

1. **Test Suite Verification:**
   Run the automated test suite before any deployment:
   ```bash
   make test
   ```
   *Expected:* `134 passed` in < 1.0s.

2. **Smoke Test Verification:**
   ```bash
   make smoke
   ```
   *Expected:* Clean headless execution of `app.py`, `pages/2_Quote_Parser.py`, and `pages/3_Compare_Quotes.py`.

3. **Mail Server Connectivity Check:**
   Run the standalone connection diagnostic:
   ```bash
   .venv/bin/python -c "from imap_checker import test_imap_connection; print(test_imap_connection())"
   ```
   *Expected:* `(True, 'Connected (INBOX: <count> messages)')`.

---

## 5. Backup & Disaster Recovery

The system's state resides entirely in the `data/` and `outputs/` directories:
- **`outputs/rfq_log.csv`**: Transaction ledger of all drafted/exported RFQs.
- **`outputs/quotes.csv`**: Database of all parsed and approved supplier quotations.
- **`data/suppliers.csv`**: Supplier master list.
- **`data/banned_terms.txt`**: Security redaction catalog.

**Recommended Daily Cron Backup:**
```bash
0 2 * * * tar -czf /backups/procurement_data_$(date +\%F).tar.gz /opt/procurement-agent/data /opt/procurement-agent/outputs
```

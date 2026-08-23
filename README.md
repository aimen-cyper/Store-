# DHĀT STORE — AIMEN

AIMEN is the canonical unified application for DHĀT STORE.

## التشغيل

```bash
python -m pip install -r requirements.txt
uvicorn aimen:app --host 0.0.0.0 --port 8000
```

ثم افتح:

- `/` — لوحة البداية
- `/store` — واجهة المتجر
- `/admin` — مدخل الإدارة
- `/docs` — توثيق API التفاعلي
- `/health` — فحص الحالة

## الفكرة

تم تجميع منطق المتجر التشغيلي في ملف واحد:

```text
AIMEN
└── aimen.py
```

ويحتوي الملف على قاعدة البيانات، المصادقة، RBAC، المستخدمين، التصنيفات، الخدمات، التسعير، الموردين، ربط الموردين بالخدمات، اختيار المورد، reconciliation، المحافظ، ledger، الإيداعات، المدفوعات، الكوبونات، الطلبات، الدعم، الإشعارات، التدقيق، التحليلات، APIs، واجهات HTML، وTelegram webhook.

## الإعدادات

انسخ `.env.example` واضبط:

- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `OWNER_TELEGRAM_ID`
- `SESSION_DAYS`
- `TELEGRAM_AUTH_MAX_AGE`
- `CORS_ORIGINS`
- `AIMEN_SECRET_PEPPER`

للاستخدام الإنتاجي المالي استخدم PostgreSQL وليس SQLite.

## الموردون

من خلال API الإدارة تستطيع إضافة المورد، تعديل بياناته، تفعيل/تعطيله، تحديد الأولوية، تحديد العمليات المدعومة، ثم ربطه بأي خدمة بواسطة `external_service_id`.

المفتاح السري للمورد لا يعاد في استجابات API.

## مبدأ الطلبات

كل طلب عميل يحتاج `Idempotency-Key`. الخصم من المحفظة يتم عبر ledger idempotency، ونتيجة المورد غير المعروفة لا يعاد إرسالها تلقائياً؛ تسجل `UNKNOWN` وتنتظر reconciliation.

## ملاحظة عن المستودع القديم

قد تبقى ملفات البنية السابقة، الاختبارات، التوثيق، وملفات التشغيل في Git لأغراض التاريخ والتوافق. **مصدر التطبيق التشغيلي الموحد هو `aimen.py`**. لا تعتمد على الوحدات القديمة لتشغيل المتجر.

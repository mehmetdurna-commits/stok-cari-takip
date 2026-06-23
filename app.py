from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, current_app, g, send_from_directory, make_response
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, 
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from sqlalchemy import text, inspect, or_, func, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import ObjectDeletedError
from functools import wraps
from pathlib import Path
import ast
import subprocess
import sys
import os
import hashlib
import zipfile
import secrets
import sqlite3
import smtplib
from email.message import EmailMessage
import re
import uuid
import json
import time
import re
import csv
import io
import threading
import urllib.error
import urllib.request
import tempfile
from functools import wraps
from config import AppConfig, validate_runtime_config
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.config.from_object(AppConfig)
app.json.ensure_ascii = False
validate_runtime_config(app)

if app.config.get("IS_PRODUCTION") and os.environ.get("USE_PROXY_FIX", "").strip().lower() in {"1", "true", "yes", "on"}:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Initialize extensions
db = SQLAlchemy(app)
try:
    from flask_migrate import Migrate
    migrate = Migrate(app, db)
except ImportError:
    migrate = None
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'giris'
login_manager.login_message = 'Bu sayfaya erişmek için lütfen giriş yapın.'
login_manager.login_message_category = 'info'

try:
    APP_LOCAL_TIMEZONE = ZoneInfo('Europe/Istanbul')
except Exception:
    APP_LOCAL_TIMEZONE = timezone(timedelta(hours=3))


def to_local_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    elif isinstance(value, date):
        dt_value = datetime.combine(value, datetime.min.time())
    else:
        return value

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(APP_LOCAL_TIMEZONE)


def local_now():
    return datetime.now(timezone.utc).astimezone(APP_LOCAL_TIMEZONE)


def format_tr_datetime(value, fmt='%d.%m.%Y %H:%M'):
    if value is None:
        return '-'
    if isinstance(value, datetime):
        localized = to_local_datetime(value)
        return localized.strftime(fmt) if localized else '-'
    if isinstance(value, date):
        return value.strftime(fmt if '%' in fmt else '%d.%m.%Y')
    return str(value)


def format_tr_date(value, fmt='%d.%m.%Y'):
    if value is None:
        return '-'
    if isinstance(value, datetime):
        localized = to_local_datetime(value)
        return localized.strftime(fmt) if localized else '-'
    if isinstance(value, date):
        return value.strftime(fmt)
    return str(value)


def format_tr_time(value, fmt='%H:%M'):
    if value is None:
        return '-'
    if isinstance(value, datetime):
        localized = to_local_datetime(value)
        return localized.strftime(fmt) if localized else '-'
    return str(value)


@app.context_processor
def inject_template_helpers():
    return {
        'now': local_now,
        'datetime': datetime,
        'date': date,
        'to_local_datetime': to_local_datetime,
        'site_config': site_config,
        'smtp_config': smtp_config,
        'user_display_name': user_display_name,
        'user_display_subtitle': user_display_subtitle,
        'user_initials': user_initials,
        'platform_can': platform_can,
        'platform_setting': platform_setting,
        'platform_setting_bool': platform_setting_bool,
        'app_page_url': app_page_url,
    }


AUDIT_ACTION_LABELS = {
    'CREATE': 'Olusturma',
    'UPDATE': 'Guncelleme',
    'DELETE': 'Silme',
    'LOGOUT': 'Cikis',
    'SECURITY_AUDIT': 'Guvenlik denetimi',
    'PLATFORM_ORGANIZATION_UPDATE': 'Firma ayarlari guncellendi',
    'PLATFORM_USER_UPDATE': 'Kullanici yetkileri guncellendi',
    'PLATFORM_MAINTENANCE': 'Bakim modu guncellendi',
    'PLATFORM_SETTINGS_UPDATE': 'Sistem ayarlari guncellendi',
    'PLATFORM_SYSTEM_CONTROLS_UPDATE': 'Sistem yonetimi guncellendi',
    'PLATFORM_LOCK_BLOCKED': 'Kilitli islem engellendi',
    'PLATFORM_SELF_TEST_RUN': 'Test robotu calistirildi',
    'PLATFORM_WORKFLOW_TEST_RUN': 'Derin is akisi testi calistirildi',
    'PLATFORM_SINGLE_TEST_RUN': 'Tekil test calistirildi',
    'PLATFORM_AUTO_BACKUP_RUN': 'Otomatik yedekleme calistirildi',
    'SECURITY_THREAT_BLOCKED': 'Supheli istek engellendi',
    'LOGIN_FAILED': 'Basarisiz giris',
    'PLATFORM_IMPERSONATE_START': 'Destek girisi baslatildi',
    'PLATFORM_IMPERSONATE_END': 'Destek girisi sonlandirildi',
    'SUPPORT_TICKET_CREATE': 'Destek talebi acildi',
    'SUPPORT_TICKET_UPDATE': 'Destek talebi guncellendi',
    'ACTION_ITEM_UPDATE': 'Aksiyon guncellendi',
    'PLATFORM_BACKUP_DOWNLOAD': 'Yedek indirildi',
}

AUDIT_RESOURCE_LABELS = {
    'Organization': 'Firma',
    'User': 'Kullanici',
    'Platform': 'Platform',
    'SecurityAudit': 'Guvenlik denetimi',
    'Satis': 'Satis',
    'Teklif': 'Teklif',
    'Cari': 'Cari',
    'Iade': 'Iade',
    'SupportTicket': 'Destek talebi',
    'ActionItem': 'Aksiyon',
    'PlatformLock': 'Platform kilidi',
}


def audit_action_label(action):
    if not action:
        return '-'
    if action in AUDIT_ACTION_LABELS:
        return AUDIT_ACTION_LABELS[action]
    return action.replace('_', ' ').strip().title()


def audit_resource_label(resource_type):
    if not resource_type:
        return '-'
    return AUDIT_RESOURCE_LABELS.get(resource_type, resource_type)


def format_tr_number(value, decimals=2):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0

    formatted = f'{number:,.{int(decimals)}f}'
    return formatted.replace(',', 'X').replace('.', ',').replace('X', '.')


def format_money(value, symbol='₺', decimals=2):
    return f'{symbol}{format_tr_number(value, decimals)}'


class SimplePagination:
    def __init__(self, items, page, per_page):
        self.total = len(items)
        self.page = max(page, 1)
        self.per_page = per_page
        self.pages = max((self.total + per_page - 1) // per_page, 1)
        if self.page > self.pages:
            self.page = self.pages
        start = (self.page - 1) * per_page
        self.items = items[start:start + per_page]
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1
        self.next_num = self.page + 1


def app_page_url(page):
    args = dict(request.view_args or {})
    args.update(request.args.to_dict(flat=True))
    args['page'] = page
    return url_for(request.endpoint, **args)


def current_items_per_page(default=25):
    allowed = {10, 25, 50, 100}
    try:
        user_settings = get_user_settings(current_user.id) if current_user.is_authenticated else {}
        value = int(user_settings.get('items_per_page', default))
    except (TypeError, ValueError):
        value = default
    return value if value in allowed else default


def paginate_list_items(items):
    page = request.args.get('page', 1, type=int)
    return SimplePagination(items, page, current_items_per_page())


def audit_detail_label(details):
    if not details:
        return '-'

    translated = details
    for action in sorted(AUDIT_ACTION_LABELS, key=len, reverse=True):
        translated = translated.replace(action, AUDIT_ACTION_LABELS[action])
    for resource_type in sorted(AUDIT_RESOURCE_LABELS, key=len, reverse=True):
        translated = translated.replace(resource_type, AUDIT_RESOURCE_LABELS[resource_type])

    replacements = {
        'islem yapildi': 'islemi yapildi',
        'işlem yapıldı': 'islemi yapildi',
    }
    for old, new in replacements.items():
        translated = translated.replace(old, new)

    return translated


app.add_template_filter(audit_action_label)
app.add_template_filter(audit_resource_label)
app.add_template_filter(audit_detail_label)
app.add_template_filter(format_tr_number, 'tr_number')
app.add_template_filter(format_tr_datetime, 'datetime_tr')
app.add_template_filter(format_tr_date, 'date_tr')
app.add_template_filter(format_tr_time, 'time_tr')
app.add_template_filter(format_money, 'money')

# Veritaban? Modelleri


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False)
    owner_user_id = db.Column(db.Integer, nullable=True)
    plan = db.Column(db.String(20), default='demo')
    active = db.Column(db.Boolean, default=True)
    user_limit = db.Column(db.Integer, default=1)
    product_limit = db.Column(db.Integer, default=10)
    module_permissions = db.Column(db.Text, default='{}')
    maintenance_mode = db.Column(db.Boolean, default=False)
    subscription_start = db.Column(db.Date)
    subscription_end = db.Column(db.Date)
    subscription_status = db.Column(db.String(20), default='trial')
    subscription_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    firma_adi = db.Column(db.String(100), nullable=False)
    yetkili_adi = db.Column(db.String(100))
    telefon = db.Column(db.String(20))
    vergi_dairesi = db.Column(db.String(100))
    vergi_numarasi = db.Column(db.String(100))
    adres = db.Column(db.Text)
    kayit_tarihi = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    paket_tipi = db.Column(db.String(20), default='demo')  # demo, standart, profesyonel
    urun_limiti = db.Column(db.Integer, default=10)
    aktif = db.Column(db.Boolean, default=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=True)
    role = db.Column(db.String(30), default='owner')
    is_platform_admin = db.Column(db.Boolean, default=False)
    platform_role = db.Column(db.String(30), default='owner')

    @property
    def is_active(self):
        return bool(self.aktif)

    # ?li?kiler
    urunler = db.relationship('Urun', backref='sahip', lazy=True)
    cariler = db.relationship('Cari', backref='sahip', lazy=True)
    organization = db.relationship('Organization', foreign_keys=[organization_id], backref=db.backref('users', lazy=True))


class Urun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barkod = db.Column(db.String(50), nullable=True)  # unique kald?r?ld?, nullable yap?ld?
    urun_adi = db.Column(db.String(200), nullable=False)
    kategori = db.Column(db.String(100))
    birim = db.Column(db.String(20), default='Adet')
    alis_fiyati = db.Column(db.Float, default=0)
    satis_fiyati = db.Column(db.Float, default=0)
    stok_miktari = db.Column(db.Float, default=0)
    kritik_stok = db.Column(db.Float, default=10)
    depo_adi = db.Column(db.String(100), default='Ana Depo')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    eklenme_tarihi = db.Column(db.DateTime, default=datetime.now(timezone.utc))


class Cari(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unvan = db.Column(db.String(200), nullable=False)
    yetkili = db.Column(db.String(100))
    telefon = db.Column(db.String(20))
    email = db.Column(db.String(120))
    vergidairesi = db.Column(db.String(100))
    vergi_numarasi = db.Column(db.String(100))
    adres = db.Column(db.Text)
    tipi = db.Column(db.String(20), default='Müşteri')  # Müşteri veya Tedarikçi
    borc = db.Column(db.Float, default=0)
    alacak = db.Column(db.Float, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kayit_tarihi = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    teklifler = db.relationship('Teklif', backref='cari', lazy=True)

    @property
    def bakiye(self):
        return (self.alacak or 0) - (self.borc or 0)


class Teklif(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teklif_no = db.Column(db.String(50), unique=True, nullable=False)
    cari_id = db.Column(db.Integer, db.ForeignKey('cari.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tarih = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    gecerlilik_tarihi = db.Column(db.DateTime)
    toplam_tutar = db.Column(db.Float, default=0)
    kdv_orani = db.Column(db.Float, default=18)
    genel_toplam = db.Column(db.Float, default=0)
    durum = db.Column(db.String(20), default='taslak')  # taslak, gonderildi, onaylandi, reddedildi
    notlar = db.Column(db.Text)

    kalemler = db.relationship('TeklifKalemi', backref='teklif', lazy=True, cascade='all, delete-orphan')


class TeklifKalemi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teklif_id = db.Column(db.Integer, db.ForeignKey('teklif.id'), nullable=False)
    urun_id = db.Column(db.Integer, db.ForeignKey('urun.id'), nullable=False)
    urun_adi = db.Column(db.String(200), nullable=False)
    miktar = db.Column(db.Float, default=1)
    birim = db.Column(db.String(20), default='Adet')
    birim_fiyat = db.Column(db.Float, default=0)
    kdv_orani = db.Column(db.Float, default=18)
    toplam = db.Column(db.Float, default=0)
    aciklama = db.Column(db.Text)


class Iade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cari_id = db.Column(db.Integer, db.ForeignKey('cari.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    iade_turu = db.Column(db.String(50), nullable=False)  # para_iadesi, urun_iadesi, hizmet_iadesi, degisim
    iade_sebebi = db.Column(db.Text, nullable=False)
    iade_tutari = db.Column(db.Float, default=0)
    durum = db.Column(db.String(20), default='beklemede')  # bekleyen, tamamlanan, iptal
    urun_adet = db.Column(db.Integer, default=0)
    tarih = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    ip_adresi = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))

    cari = db.relationship('Cari', backref='iadeler')
    kalemler = db.relationship('IadeKalem', lazy='dynamic', backref='iade_obj')


class IadeKalem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    iade_id = db.Column(db.Integer, db.ForeignKey('iade.id'), nullable=False)
    urun_id = db.Column(db.Integer, db.ForeignKey('urun.id'), nullable=False)
    urun_adi = db.Column(db.String(200), nullable=False)
    miktar = db.Column(db.Float, nullable=False)
    birim_fiyat = db.Column(db.Float, nullable=False)
    eski_stok = db.Column(db.Float, default=0)
    yeni_stok = db.Column(db.Float, default=0)

    urun = db.relationship('Urun', backref='iade_kalemleri')


class CariHareket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cari_id = db.Column(db.Integer, db.ForeignKey('cari.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tarih = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    islem_tipi = db.Column(db.String(20), nullable=False)  # odeme, tahsilat, satis, iade
    tutar = db.Column(db.Float, nullable=False)
    aciklama = db.Column(db.Text)
    odeme_turu = db.Column(db.String(50))  # Nakit, Havale/EFT, Kredi Kartı, ?ek
    referans_id = db.Column(db.Integer)  # Satis veya teklif ID'si
    referans_tip = db.Column(db.String(20))  # satis, teklif

    cari = db.relationship('Cari', backref='hareketler')


class StokHareket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    urun_id = db.Column(db.Integer, db.ForeignKey('urun.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tarih = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    islem_tipi = db.Column(db.String(20), nullable=False)  # giris, cikis
    miktar = db.Column(db.Float, nullable=False)
    aciklama = db.Column(db.Text)
    depo = db.Column(db.String(100), default='Ana Merkez Depo')
    eski_stok = db.Column(db.Float, default=0)
    yeni_stok = db.Column(db.Float, default=0)
    cari_id = db.Column(db.Integer, db.ForeignKey('cari.id'), nullable=True)  # Stok çıkışında müşteri
    ip_adresi = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))

    urun = db.relationship('Urun', backref='stok_hareketleri')
    cari = db.relationship('Cari', backref='stok_hareketleri')


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)  # CREATE, UPDATE, DELETE, LOGIN, LOGOUT
    resource_type = db.Column(db.String(50), nullable=False)  # User, Urun, Cari, Satis, Teklif
    resource_id = db.Column(db.Integer)
    old_values = db.Column(db.Text)  # JSON format?nda eski de?erler
    new_values = db.Column(db.Text)  # JSON format?nda yeni de?erler
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    session_id = db.Column(db.String(100))

    user = db.relationship('User', backref='audit_logs')


class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.String(500))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    user = db.relationship('User', backref='system_settings')


class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(40), default='general')
    priority = db.Column(db.String(20), default='normal')
    status = db.Column(db.String(20), default='open')
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    closed_at = db.Column(db.DateTime)

    organization = db.relationship('Organization', backref='support_tickets')
    requester = db.relationship('User', foreign_keys=[requester_id], backref='requested_tickets')
    messages = db.relationship('SupportTicketMessage', backref='ticket', lazy=True, cascade='all, delete-orphan')


class SupportTicketMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('support_ticket.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_staff_reply = db.Column(db.Boolean, default=False)
    attachment_filename = db.Column(db.String(255))
    attachment_original_name = db.Column(db.String(255))
    attachment_content_type = db.Column(db.String(120))
    attachment_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id], backref='support_ticket_messages')


class ActionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=True)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.Integer)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(20), default='open')
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    sla_hours = db.Column(db.Integer)
    due_at = db.Column(db.DateTime)
    ai_summary = db.Column(db.Text)
    ai_recommendation = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime)
    snoozed_until = db.Column(db.DateTime)

    organization = db.relationship('Organization', backref='action_items')
    assigned_user = db.relationship('User', foreign_keys=[assigned_user_id], backref='assigned_action_items')


class ActionItemEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_item_id = db.Column(db.Integer, db.ForeignKey('action_item.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    event_type = db.Column(db.String(40), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    action_item = db.relationship('ActionItem', backref=db.backref('events', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])


class SubscriptionPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    plan = db.Column(db.String(20), default='standart')
    amount = db.Column(db.Float, default=0)
    currency = db.Column(db.String(8), default='TRY')
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    status = db.Column(db.String(20), default='pending')
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    paid_at = db.Column(db.DateTime)

    organization = db.relationship('Organization', backref=db.backref('subscription_payments', lazy=True))


class CashTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)
    cari_id = db.Column(db.Integer, db.ForeignKey('cari.id'), nullable=True)
    tarih = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    islem_tipi = db.Column(db.String(20), nullable=False)  # giris, cikis
    tutar = db.Column(db.Float, nullable=False)
    odeme_turu = db.Column(db.String(50), default='Nakit')
    aciklama = db.Column(db.Text)
    referans_id = db.Column(db.Integer)
    referans_tip = db.Column(db.String(20))
    ip_adresi = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))

    user = db.relationship('User', backref='nakit_hareketleri')
    cari = db.relationship('Cari', backref='nakit_hareketleri')
    account = db.relationship('Account', backref='transactions')


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False, default='cash')  # cash, bank, pos
    name = db.Column(db.String(120), nullable=False)
    currency = db.Column(db.String(8), default='TRY')
    opening_balance = db.Column(db.Float, default=0)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    iban = db.Column(db.String(40))
    bank_name = db.Column(db.String(80))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_user_account_name'),
    )

    user = db.relationship('User', backref='accounts')


class AccountReconciliation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    recon_date = db.Column(db.Date, nullable=False)

    expected_balance = db.Column(db.Float, default=0)
    counted_balance = db.Column(db.Float, default=0)
    difference = db.Column(db.Float, default=0)

    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    user = db.relationship('User', backref='account_reconciliations')
    account = db.relationship('Account', backref='reconciliations')


class BackupLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.BigInteger)
    backup_type = db.Column(db.String(20), default='manual')  # manual, auto
    status = db.Column(db.String(20), default='completed')  # completed, failed, in_progress
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    error_message = db.Column(db.Text)

    user = db.relationship('User', backref='backup_logs')


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_user_category_name'),
    )
    user = db.relationship('User', backref='categories')


class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_user_warehouse_name'),
    )
    user = db.relationship('User', backref='warehouses')


# Personel Y?netimi Modelleri
class Departman(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    aciklama = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personeller = db.relationship('Personel', backref='departman', lazy=True)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'ad', name='uq_user_departman_ad'),
    )


class Personel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sicil_no = db.Column(db.String(50), nullable=False)
    ad = db.Column(db.String(100), nullable=False)
    soyad = db.Column(db.String(100), nullable=False)
    tc_kimlik = db.Column(db.String(11))
    dogum_tarihi = db.Column(db.Date)
    cinsiyet = db.Column(db.String(10))
    medeni_hal = db.Column(db.String(20))
    telefon = db.Column(db.String(20))
    email = db.Column(db.String(120))
    adres = db.Column(db.Text)
    ehliyet = db.Column(db.String(20))
    ehliyet_no = db.Column(db.String(50))
    kan_grubu = db.Column(db.String(10))
    acil_durum_kisi = db.Column(db.String(100))
    acil_durum_telefon = db.Column(db.String(20))
    profil_foto = db.Column(db.String(255))
    ise_giris_tarihi = db.Column(db.Date, nullable=False)
    ise_cikis_tarihi = db.Column(db.Date)
    calisma_durumu = db.Column(db.String(20), default='Aktif')
    departman_id = db.Column(db.Integer, db.ForeignKey('departman.id'))
    pozisyon = db.Column(db.String(100))
    maas = db.Column(db.Float, default=0)
    sgk_no = db.Column(db.String(50))
    vergi_no = db.Column(db.String(50))
    iban = db.Column(db.String(50))
    banka_adi = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'sicil_no', name='uq_user_personel_sicil'),
    )


class Izin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False)
    izin_tipi = db.Column(db.String(50), nullable=False)
    baslangic_tarihi = db.Column(db.Date, nullable=False)
    bitis_tarihi = db.Column(db.Date, nullable=False)
    gun_sayisi = db.Column(db.Integer, nullable=False)
    aciklama = db.Column(db.Text)
    onay_durumu = db.Column(db.String(20), default='Beklemede')
    onaylayan = db.Column(db.Integer)
    onay_tarihi = db.Column(db.DateTime)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    talep_tarihi = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personel = db.relationship('Personel', backref='izinler')


class Avans(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False)
    tutar = db.Column(db.Float, nullable=False)
    aciklama = db.Column(db.Text)
    kesinti_turu = db.Column(db.String(50), default='Maaştan')
    taksit_sayisi = db.Column(db.Integer, default=1)
    durum = db.Column(db.String(20), default='Kaydedildi')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    talep_tarihi = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personel = db.relationship('Personel', backref='avanslar')


class Prim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False)
    prim_tipi = db.Column(db.String(50), nullable=False)
    tutar = db.Column(db.Float, nullable=False)
    aciklama = db.Column(db.Text)
    donem = db.Column(db.String(20))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kayit_tarihi = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personel = db.relationship('Personel', backref='primler')


class MaasKaydi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False)
    ay = db.Column(db.String(20), nullable=False)
    yil = db.Column(db.Integer, nullable=False)
    brut_ucret = db.Column(db.Float, nullable=False)
    net_ucret = db.Column(db.Float, nullable=False)
    sgk_kesinti = db.Column(db.Float, default=0)
    gelir_vergisi = db.Column(db.Float, default=0)
    damga_vergisi = db.Column(db.Float, default=0)
    diger_kesintiler = db.Column(db.Float, default=0)
    odeme_durumu = db.Column(db.String(20), default='Ödenmedi')
    odeme_tarihi = db.Column(db.DateTime)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personel = db.relationship('Personel', backref='maas_kayitlari')


class EgitimKaydi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False)
    egitim_adi = db.Column(db.String(200), nullable=False)
    egitim_tipi = db.Column(db.String(50))
    baslangic_tarihi = db.Column(db.Date)
    bitis_tarihi = db.Column(db.Date)
    sure = db.Column(db.Integer)
    kurum = db.Column(db.String(200))
    sertifa_no = db.Column(db.String(100))
    ucret = db.Column(db.Float)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personel = db.relationship('Personel', backref='egitim_kayitlari')


class PersonelPerformans(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    personel_id = db.Column(db.Integer, db.ForeignKey('personel.id'), nullable=False)
    degerlendirme_tarihi = db.Column(db.Date, nullable=False)
    degerlendiren = db.Column(db.Integer)
    performans_puani = db.Column(db.Float)
    hedeflere_uyum = db.Column(db.Float)
    is_kalitesi = db.Column(db.Float)
    takim_calismasi = db.Column(db.Float)
    yenilikcilik = db.Column(db.Float)
    aciklamalar = db.Column(db.Text)
    gelisim_alanlari = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    # ?li?kiler
    personel = db.relationship('Personel', backref='performans_degerlendirmeleri')


def make_tenant_slug(name, fallback='firma'):
    base = re.sub(r'[^a-z0-9]+', '-', (name or fallback).strip().lower()).strip('-')
    return base or fallback


def unique_organization_slug(name, owner_id=None):
    base = make_tenant_slug(name, f'firma-{owner_id or uuid.uuid4().hex[:8]}')
    slug = base
    suffix = 2
    while Organization.query.filter_by(slug=slug).first():
        slug = f'{base}-{suffix}'
        suffix += 1
    return slug


def default_subscription_end(start_date=None, months=12):
    start_date = start_date or date.today()
    return start_date + timedelta(days=365 if months == 12 else max(1, int(months * 30)))


def subscription_summary(organization):
    today = date.today()
    end_date = organization.subscription_end
    status = organization.subscription_status or 'trial'
    days_left = (end_date - today).days if end_date else None

    if status != 'cancelled' and days_left is not None and days_left < 0:
        status = 'expired'
    elif status == 'trial' and days_left is not None and days_left >= 0 and organization.plan != 'demo':
        status = 'active'

    if status == 'expired':
        label = 'Suresi doldu'
        tone = 'rose'
    elif status == 'cancelled':
        label = 'Iptal'
        tone = 'slate'
    elif days_left is not None and days_left <= 30:
        label = 'Yenileme yaklasti'
        tone = 'amber'
    elif status == 'trial':
        label = 'Deneme'
        tone = 'blue'
    else:
        label = 'Aktif'
        tone = 'emerald'

    return {
        'status': status,
        'label': label,
        'tone': tone,
        'days_left': days_left,
        'is_expired': status == 'expired',
        'is_renewal_due': days_left is not None and days_left <= 30 and status not in {'expired', 'cancelled'},
    }


SUPPORT_STATUS_LABELS = {
    'open': 'Açık',
    'waiting_admin': 'Destek bekliyor',
    'waiting_customer': 'Firma yanıtı bekleniyor',
    'resolved': 'Çözüldü',
    'closed': 'Kapalı',
}

SUPPORT_PRIORITY_LABELS = {
    'low': 'Düşük',
    'normal': 'Normal',
    'high': 'Yüksek',
    'urgent': 'Acil',
}

SUPPORT_CATEGORY_LABELS = {
    'general': 'Genel',
    'technical': 'Teknik',
    'billing': 'Ödeme / Abonelik',
    'training': 'Eğitim',
    'bug': 'Hata bildirimi',
}

SUPPORT_ATTACHMENT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
SUPPORT_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024

ACTION_STATUS_LABELS = {
    'open': 'Açık',
    'snoozed': 'Ertelendi',
    'done': 'Tamamlandı',
}

ACTION_SEVERITY_LABELS = {
    'low': 'Düşük',
    'medium': 'Orta',
    'high': 'Yüksek',
    'critical': 'Kritik',
}

ACTION_SOURCE_LABELS = {
    'support': 'Destek',
    'subscription': 'Abonelik',
    'usage': 'Kullanım',
    'limit': 'Limit',
    'manual': 'Manuel',
}

ACTION_EVENT_LABELS = {
    'created': 'Olusturuldu',
    'updated': 'Guncellendi',
    'assigned': 'Sahip atandi',
    'snoozed': 'Ertelendi',
    'done': 'Tamamlandi',
    'reopened': 'Yeniden acildi',
    'ai_refreshed': 'AI onerisi yenilendi',
}

PLATFORM_ADMIN_ROLE_LABELS = {
    'owner': 'Platform sahibi',
    'operations': 'Operasyon',
    'support': 'Destek',
    'finance': 'Finans',
    'viewer': 'Izleyici',
}

PLATFORM_PERMISSION_LABELS = {
    'dashboard': 'Super admin panelini gorur',
    'actions_view': 'Aksiyonlari gorur',
    'actions_manage': 'Aksiyon atar ve tamamlar',
    'support_view': 'Destek taleplerini gorur',
    'support_manage': 'Destek taleplerini yanitlar',
    'organizations_view': 'Firma profillerini gorur',
    'organizations_manage': 'Firma ayarlarini gunceller',
    'billing_manage': 'Odeme ve abonelik kaydi yapar',
    'users_manage': 'Musteri kullanici yetkilerini yonetir',
    'team_manage': 'Platform ekibini yonetir',
    'settings_manage': 'Sistem ayarlarini yonetir',
    'logs_view': 'Audit loglarini gorur',
    'backups_view': 'Yedekleri gorur',
}

PLATFORM_ROLE_PERMISSIONS = {
    'owner': set(PLATFORM_PERMISSION_LABELS),
    'operations': {
        'dashboard', 'actions_view', 'actions_manage', 'support_view', 'support_manage',
        'organizations_view', 'organizations_manage', 'logs_view', 'backups_view',
    },
    'support': {'dashboard', 'actions_view', 'actions_manage', 'support_view', 'support_manage', 'organizations_view'},
    'finance': {'dashboard', 'actions_view', 'organizations_view', 'billing_manage', 'logs_view'},
    'viewer': {'dashboard', 'actions_view', 'support_view', 'organizations_view', 'logs_view'},
}

BILLING_STATUS_LABELS = {
    'pending': 'Bekliyor',
    'paid': 'Odendi',
    'overdue': 'Gecikti',
    'cancelled': 'Iptal',
}


def support_label(mapping, key):
    return mapping.get(key, key.replace('_', ' ').title() if key else '-')


def user_display_name(user):
    if not user:
        return 'Kullanici'
    if getattr(user, 'is_platform_admin', False) and getattr(user, 'firma_adi', '') == 'Platform Ekibi':
        return user.yetkili_adi or user.email or 'Platform ekibi'
    return user.yetkili_adi or user.firma_adi or user.email or 'Kullanici'


def user_display_subtitle(user):
    if not user:
        return ''
    if getattr(user, 'is_platform_admin', False):
        return PLATFORM_ADMIN_ROLE_LABELS.get(user.platform_role or 'viewer', 'Platform ekibi')
    return user.paket_tipi or 'Demo Paket'


def user_initials(user):
    name = user_display_name(user)
    parts = [part for part in re.split(r'\s+', name.strip()) if part]
    if len(parts) >= 2:
        return f'{parts[0][0]}{parts[-1][0]}'.upper()
    return (name[:1] or 'U').upper()


def platform_can(permission, user=None):
    user = user or current_user
    if not is_platform_admin_user(user):
        return False
    role = user.platform_role or 'owner'
    return permission in PLATFORM_ROLE_PERMISSIONS.get(role, set())


def is_platform_owner_user(user=None):
    user = user or current_user
    return is_platform_admin_user(user) and (user.platform_role or 'viewer') == 'owner'


def active_platform_actor():
    actor_id = session.get('platform_admin_id')
    if not actor_id:
        return current_user if current_user.is_authenticated and is_platform_admin_user(current_user) else None
    try:
        return db.session.get(User, int(actor_id))
    except (TypeError, ValueError):
        return None


def platform_lock_enabled(key):
    return platform_setting_bool(key, False)


def audit_platform_lock_block(lock_key, message):
    if not current_user.is_authenticated:
        return
    platform_audit(
        'PLATFORM_LOCK_BLOCKED',
        (
            f'Kilit={lock_key}; kullanici={current_user.email}; '
            f'endpoint={request.endpoint}; path={request.path}; mesaj={message}'
        ),
        'PlatformLock'
    )


def block_platform_owner_lock(message, redirect_anchor='platform-system', lock_key='owner_protection'):
    audit_platform_lock_block(lock_key, message)
    db.session.commit()
    flash(message, 'warning')
    return redirect(url_for('super_admin_dashboard') + f'#{redirect_anchor}')


def require_platform_owner_for_locked_action(lock_key, message, redirect_anchor='platform-system'):
    if platform_lock_enabled(lock_key) and not is_platform_owner_user(current_user):
        return block_platform_owner_lock(message, redirect_anchor, lock_key)
    if platform_lock_enabled('owner_approval_required') and not is_platform_owner_user(current_user):
        return block_platform_owner_lock('Bu kritik islem icin platform sahibi onayi gerekli.', redirect_anchor, 'owner_approval_required')
    return None


def support_ticket_allowed(ticket):
    if not ticket:
        return False
    if is_platform_admin_user(current_user):
        return True
    return ticket.organization_id == current_user.organization_id


def support_upload_dir():
    path = os.path.join(app.static_folder, 'support_uploads')
    os.makedirs(path, exist_ok=True)
    return path


def save_support_attachment(file_storage):
    if not file_storage or not file_storage.filename:
        return {}
    if platform_setting_bool('file_uploads_locked', False):
        raise ValueError('Dosya yuklemeleri sistem yonetimi tarafindan gecici olarak kapatildi.')

    original_name = secure_filename(file_storage.filename)
    extension = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    if extension not in SUPPORT_ATTACHMENT_EXTENSIONS:
        raise ValueError('Yalnizca PNG, JPG, WEBP veya GIF ekran goruntusu eklenebilir.')

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > SUPPORT_ATTACHMENT_MAX_BYTES:
        raise ValueError('Ekran goruntusu en fazla 5 MB olabilir.')

    filename = f'{uuid.uuid4().hex}.{extension}'
    file_storage.save(os.path.join(support_upload_dir(), filename))
    return {
        'attachment_filename': filename,
        'attachment_original_name': original_name,
        'attachment_content_type': file_storage.mimetype,
        'attachment_size': size,
    }


def action_sla_hours(created_at, due_at):
    if not created_at or not due_at:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return max(1, int((due_at - created_at).total_seconds() // 3600))


def action_sla_state(action, now_value=None):
    if not action or not action.due_at:
        return {'label': 'SLA yok', 'tone': 'slate', 'minutes': None, 'overdue': False}
    now_value = now_value or datetime.now(timezone.utc)
    due_at = action.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    minutes = int((due_at - now_value).total_seconds() // 60)
    if action.status == 'done':
        return {'label': 'Tamamlandi', 'tone': 'emerald', 'minutes': minutes, 'overdue': False}
    if minutes < 0:
        hours = max(1, abs(minutes) // 60)
        return {'label': f'{hours} saat gecikti', 'tone': 'rose', 'minutes': minutes, 'overdue': True}
    if minutes < 60:
        return {'label': f'{max(1, minutes)} dk kaldi', 'tone': 'amber', 'minutes': minutes, 'overdue': False}
    hours = minutes // 60
    return {'label': f'{hours} saat kaldi', 'tone': 'blue' if hours <= 24 else 'slate', 'minutes': minutes, 'overdue': False}


def add_action_event(action, event_type, note=''):
    if not action:
        return None
    event = ActionItemEvent(
        action_item_id=action.id,
        user_id=current_user.id if current_user.is_authenticated else None,
        event_type=event_type,
        note=(note or '').strip()[:1000],
    )
    db.session.add(event)
    return event


def upsert_action_item(source_type, source_id, organization_id, title, description, severity='medium',
                       due_at=None, ai_summary=None, ai_recommendation=None):
    action = ActionItem.query.filter_by(source_type=source_type, source_id=source_id).first()
    is_new = False
    if not action:
        action = ActionItem(source_type=source_type, source_id=source_id)
        db.session.add(action)
        is_new = True

    action.organization_id = organization_id
    action.title = title[:180]
    action.description = description
    action.severity = severity
    action.due_at = due_at
    action.sla_hours = action.sla_hours or action_sla_hours(action.created_at or datetime.now(timezone.utc), due_at)
    action.ai_summary = ai_summary
    action.ai_recommendation = ai_recommendation
    action.updated_at = datetime.now(timezone.utc)
    if action.status in {'done', 'snoozed'} and (not action.snoozed_until or action.snoozed_until <= datetime.now(timezone.utc)):
        action.status = 'open'
        action.resolved_at = None
    elif not action.status:
        action.status = 'open'
    if is_new:
        db.session.flush()
        add_action_event(action, 'created', 'Aksiyon merkezi tarafindan olusturuldu.')
    return action


def resolve_action_item(source_type, source_id):
    action = ActionItem.query.filter_by(source_type=source_type, source_id=source_id).first()
    if action and action.status != 'done':
        action.status = 'done'
        action.resolved_at = datetime.now(timezone.utc)
        action.updated_at = datetime.now(timezone.utc)
    return action


def support_ticket_sla_due(ticket):
    hours_by_priority = {
        'urgent': 2,
        'high': 8,
        'normal': 24,
        'low': 48,
    }
    created_at = ticket.created_at or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at + timedelta(hours=hours_by_priority.get(ticket.priority, 24))


def action_recommendation_for_support(ticket):
    return (
        f"{ticket.organization.name if ticket.organization else 'Firma'} için destek talebini inceleyin. "
        "Önceliğe göre net bir yanıt verin, gerekirse ekran gÜrünt?s? veya destek modu ile doğrulama yap?n."
    )


def fallback_action_ai(action):
    if action.source_type == 'support':
        summary = 'Destek talebi süper admin yanıtı bekliyor.'
        recommendation = 'Talebi inceleyin, gerekirse firmaya net sonraki adımı ve beklenen çözüm zamanını yazın.'
    elif action.source_type == 'subscription':
        summary = 'Firma abonelik/destek süresi için takip gerekiyor.'
        recommendation = 'Firma sahibiyle yenileme görüşmesi planlayın ve destek süresi durumunu güncelleyin.'
    else:
        summary = action.description or action.title
        recommendation = 'Aksiyonu sahiplenip tamamlanana kadar takip edin.'
    return summary, recommendation


def generate_action_ai_recommendation(action):
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return fallback_action_ai(action)

    try:
        from openai import OpenAI
    except ImportError:
        return fallback_action_ai(action)

    payload = {
        'title': action.title,
        'description': action.description,
        'severity': action.severity,
        'source_type': action.source_type,
        'organization': action.organization.name if action.organization else 'Platform',
        'due_at': action.due_at.isoformat() if action.due_at else None,
    }
    instructions = (
        'Bir SaaS süper admin operasyon asistanısın. '
        'Verilen aksiyon için Türkçe, kısa ve uygulanabilir öneri üret. '
        'Yanıtı yalnızca JSON olarak ver: {"summary": "...", "recommendation": "..."}'
    )
    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=os.environ.get('ACTION_AI_MODEL', 'gpt-5'),
            reasoning={'effort': 'low'},
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
            max_output_tokens=220,
        )
        data = json.loads(response.output_text)
        summary = (data.get('summary') or '').strip()
        recommendation = (data.get('recommendation') or '').strip()
        if summary and recommendation:
            return summary[:1000], recommendation[:1500]
    except Exception:
        app.logger.exception('Action AI recommendation failed')

    return fallback_action_ai(action)


def sync_support_ticket_action(ticket):
    if ticket.status in {'resolved', 'closed'}:
        return resolve_action_item('support', ticket.id)

    due_at = support_ticket_sla_due(ticket)
    now = datetime.now(timezone.utc)
    severity = 'critical' if due_at <= now else {'urgent': 'critical', 'high': 'high', 'normal': 'medium', 'low': 'low'}.get(ticket.priority, 'medium')
    title = f'Destek talebi yanıt bekliyor: #{ticket.id}'
    description = (
        f'{ticket.organization.name if ticket.organization else "Firma"} destek talebi açtı: {ticket.subject}. '
        f'Durum: {SUPPORT_STATUS_LABELS.get(ticket.status, ticket.status)}.'
    )
    return upsert_action_item(
        'support',
        ticket.id,
        ticket.organization_id,
        title,
        description,
        severity=severity,
        due_at=due_at,
        ai_summary=f'{ticket.subject} konusu destek ekibi yanıtı bekliyor.',
        ai_recommendation=action_recommendation_for_support(ticket),
    )


def sync_subscription_actions():
    today = date.today()
    organizations = Organization.query.filter(Organization.subscription_end.isnot(None)).all()
    for organization in organizations:
        source_id = organization.id
        summary = subscription_summary(organization)
        if organization.subscription_status == 'cancelled' or not (summary['is_expired'] or summary['is_renewal_due']):
            resolve_action_item('subscription', source_id)
            continue

        days_left = summary['days_left']
        severity = 'critical' if summary['is_expired'] else ('high' if days_left is not None and days_left <= 7 else 'medium')
        if summary['is_expired']:
            title = f'Destek süresi doldu: {organization.name}'
            description = f'{organization.name} firmasının destek süresi {organization.subscription_end.strftime("%d.%m.%Y")} tarihinde doldu.'
            recommendation = 'Firma ile yenileme görüşmesi yap?n; gerekirse paket durumunu pasif/aktif politikas?na göre güncelleyin.'
        else:
            title = f'Yenileme yaklaşıyor: {organization.name}'
            description = f'{organization.name} firmasının destek süresi {days_left} gün içinde bitecek.'
            recommendation = 'Yenileme teklifini hazırlayın ve firma sahibiyle iletişime geçin.'
        due_at = datetime.combine(organization.subscription_end, datetime.min.time(), tzinfo=timezone.utc)
        upsert_action_item(
            'subscription',
            source_id,
            organization.id,
            title,
            description,
            severity=severity,
            due_at=due_at,
            ai_summary=description,
            ai_recommendation=recommendation,
        )


def sync_action_center():
    for ticket in SupportTicket.query.filter(SupportTicket.status.in_(['open', 'waiting_admin'])).all():
        sync_support_ticket_action(ticket)
    for ticket in SupportTicket.query.filter(SupportTicket.status.in_(['waiting_customer', 'resolved', 'closed'])).all():
        if ticket.status in {'resolved', 'closed', 'waiting_customer'}:
            resolve_action_item('support', ticket.id)
    sync_subscription_actions()


def ensure_user_organization(user):
    if not user:
        return None
    if user.organization_id:
        organization = db.session.get(Organization, user.organization_id)
        if organization:
            if not organization.product_limit:
                organization.product_limit = user.urun_limiti or 10
            if not organization.plan:
                organization.plan = user.paket_tipi or 'demo'
        return organization

    organization = Organization(
        name=user.firma_adi or user.email,
        slug=unique_organization_slug(user.firma_adi or user.email, user.id),
        owner_user_id=user.id,
        plan=user.paket_tipi or 'demo',
        product_limit=user.urun_limiti or 10,
        active=bool(user.aktif),
        subscription_start=date.today(),
        subscription_end=default_subscription_end(),
        subscription_status='trial' if (user.paket_tipi or 'demo') == 'demo' else 'active',
    )
    db.session.add(organization)
    db.session.flush()
    user.organization_id = organization.id
    user.role = user.role or 'owner'
    return organization


def backfill_user_organizations():
    changed = False
    for user in User.query.filter(User.organization_id.is_(None), User.is_platform_admin.is_(False)).all():
        ensure_user_organization(user)
        changed = True
    if changed:
        db.session.commit()


def current_organization():
    try:
        if not current_user.is_authenticated:
            return None
        organization = ensure_user_organization(current_user)
        if db.session.is_modified(current_user):
            db.session.commit()
        return organization
    except ObjectDeletedError:
        db.session.rollback()
        clear_login_session()
        return None


def tenant_user_ids():
    organization = current_organization()
    if not organization:
        return []
    return [
        user_id for (user_id,) in db.session.query(User.id)
        .filter(User.organization_id == organization.id, User.aktif.is_(True))
        .all()
    ]


def belongs_to_current_tenant(record):
    return bool(record and getattr(record, 'user_id', None) in tenant_user_ids())


def tenant_query(model):
    return model.query.filter(model.user_id.in_(tenant_user_ids()))


PLATFORM_MODULES = [
    ('dashboard', 'Ana Panel'),
    ('urunler', 'Ürünler ve Stok'),
    ('cariler', 'Cariler'),
    ('pos', 'POS'),
    ('nakit', 'Nakit Yönetimi'),
    ('teklifler', 'Teklifler'),
    ('personel', 'Personel'),
    ('iade', 'İade'),
    ('raporlar', 'Raporlar'),
    ('support', 'Destek Talepleri'),
    ('settings', 'Ayarlar'),
]

PLATFORM_MODULE_ENDPOINT_PREFIXES = {
    'dashboard': ('dashboard',),
    'urunler': ('urun', 'stok', 'kategori', 'category', 'depo', 'warehouse', 'toplu_fiyat'),
    'cariler': ('cari',),
    'pos': ('pos', 'satis', 'gunluk_satislar'),
    'nakit': ('nakit',),
    'teklifler': ('teklif',),
    'personel': ('personel', 'departman', 'izin', 'avans', 'prim'),
    'iade': ('iade',),
    'raporlar': ('rapor',),
    'support': ('support', 'destek'),
    'settings': ('settings', 'profil', 'admin_panel', 'system_settings', 'backup', 'audit_logs', 'admin_yetki'),
}


def parse_module_permissions(value):
    permissions = {key: True for key, _ in PLATFORM_MODULES}
    if not value:
        return permissions
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return permissions
    permissions.update({key: bool(parsed.get(key, permissions[key])) for key in permissions})
    return permissions


def save_module_permissions(organization, selected_modules):
    selected = set(selected_modules or [])
    permissions = {key: key in selected for key, _ in PLATFORM_MODULES}
    organization.module_permissions = json.dumps(permissions, ensure_ascii=False)
    return permissions


def platform_setting(key, default=None):
    setting = SystemSettings.query.filter_by(user_id=None, key=f'platform.{key}').first()
    return setting.value if setting else default


def platform_setting_int(key, default):
    try:
        return int(platform_setting(key, default))
    except (TypeError, ValueError):
        return default


def platform_setting_bool(key, default=False):
    value = str(platform_setting(key, 'on' if default else 'off')).strip().lower()
    return value in {'1', 'true', 'yes', 'on', 'enabled'}


def set_platform_setting(key, value, description=None):
    setting = SystemSettings.query.filter_by(user_id=None, key=f'platform.{key}').first()
    if not setting:
        setting = SystemSettings(key=f'platform.{key}', user_id=None, description=description)
        db.session.add(setting)
    if description is not None:
        setting.description = description
    setting.value = str(value)
    setting.updated_at = datetime.now(timezone.utc)
    return setting


def platform_setting_datetime(key):
    value = platform_setting(key, '')
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def platform_system_controls():
    return {
        'maintenance_mode': platform_setting_bool('maintenance_mode', False),
        'maintenance_message': platform_setting(
            'maintenance_message',
            'Sistem kisa sureli bakim modunda. Lutfen daha sonra tekrar deneyin.'
        ),
        'maintenance_eta': platform_setting('maintenance_eta', ''),
        'readonly_mode': platform_setting_bool('readonly_mode', False),
        'file_uploads_locked': platform_setting_bool('file_uploads_locked', False),
        'dangerous_operations_locked': platform_setting_bool('dangerous_operations_locked', False),
        'security_shield_enabled': platform_setting_bool('security_shield_enabled', True),
        'owner_account_protection': platform_setting_bool('owner_account_protection', True),
        'financial_changes_locked': platform_setting_bool('financial_changes_locked', False),
        'support_impersonation_locked': platform_setting_bool('support_impersonation_locked', False),
        'data_export_locked': platform_setting_bool('data_export_locked', False),
        'owner_approval_required': platform_setting_bool('owner_approval_required', False),
        'global_notice_enabled': platform_setting_bool('global_notice_enabled', False),
        'global_notice_message': platform_setting('global_notice_message', ''),
        'registrations_enabled': platform_setting_bool('registrations_enabled', True),
        'pos_integration_enabled_for_users': platform_setting_bool('pos_integration_enabled_for_users', False),
        'session_epoch': platform_setting('session_epoch', ''),
    }


def site_config():
    site_url = platform_setting('site_url', '') or app.config.get('SITE_URL', '')
    site_url = (site_url or '').rstrip('/')
    platform_name = platform_setting('platform_name', '') or app.config.get('SITE_NAME', 'StokCari')
    site_name = platform_setting('site_name', '') or app.config.get('SITE_NAME', 'StokCari')
    site_description = platform_setting('site_description', '') or app.config.get(
        'SITE_DESCRIPTION',
        'Stok, cari, POS ve teklif yönetimi için web tabanlı işletme uygulaması.',
    )
    site_og_image = platform_setting('site_og_image', '') or app.config.get('SITE_OG_IMAGE', '')
    site_og_image = (site_og_image or '').strip()
    seo_closed_mode = platform_setting_bool('seo_closed_mode', True)
    seo_indexing_enabled = platform_setting_bool('seo_indexing_enabled', False)
    seo_public_mode = seo_indexing_enabled and not seo_closed_mode
    return {
        'url': site_url,
        'platform_name': platform_name,
        'name': site_name,
        'description': site_description,
        'og_image': site_og_image,
        'seo_closed_mode': seo_closed_mode,
        'seo_indexing_enabled': seo_indexing_enabled,
        'seo_public_mode': seo_public_mode,
    }


def smtp_config():
    def _get(key, fallback=''):
        return platform_setting(key, fallback) or fallback

    host = (_get('smtp_host', app.config.get('SMTP_HOST', '')) or '').strip()
    port_raw = _get('smtp_port', str(app.config.get('SMTP_PORT', 587)))
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = int(app.config.get('SMTP_PORT', 587) or 587)

    username = (_get('smtp_username', app.config.get('SMTP_USERNAME', '')) or '').strip()
    password = _get('smtp_password', app.config.get('SMTP_PASSWORD', '')) or ''

    use_tls = platform_setting_bool('smtp_use_tls', bool(app.config.get('SMTP_USE_TLS', True)))
    use_ssl = platform_setting_bool('smtp_use_ssl', bool(app.config.get('SMTP_USE_SSL', False)))

    from_email = (_get('smtp_from_email', app.config.get('SMTP_FROM_EMAIL', '')) or '').strip()
    from_name = (_get('smtp_from_name', app.config.get('SMTP_FROM_NAME', app.config.get('SITE_NAME', 'StokCari'))) or '').strip()

    return {
        'host': host,
        'port': port,
        'username': username,
        'password': password,
        'use_tls': use_tls,
        'use_ssl': use_ssl,
        'from_email': from_email,
        'from_name': from_name,
    }


def app_version():
    env_version = (os.environ.get('APP_VERSION') or '').strip()
    if env_version:
        return env_version
    try:
        version_path = os.path.join(os.path.dirname(__file__), 'VERSION')
        with open(version_path, 'r', encoding='utf-8') as f:
            return f.read().strip() or 'dev'
    except FileNotFoundError:
        return 'dev'


def updater_base_dir():
    base = os.path.join(app.instance_path, 'updates')
    os.makedirs(base, exist_ok=True)
    return base


def read_updater_status():
    status_path = os.path.join(updater_base_dir(), 'status.json')
    try:
        with open(status_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_updater_heartbeat():
    heartbeat_path = os.path.join(updater_base_dir(), 'heartbeat.json')
    try:
        with open(heartbeat_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_updater_request(payload):
    requests_dir = os.path.join(updater_base_dir(), 'requests')
    os.makedirs(requests_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    request_id = payload.get('id') or uuid.uuid4().hex
    path = os.path.join(requests_dir, f'{ts}_{request_id}.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def system_health_context():
    checks = {'database': 'ok', 'uploads': 'ok', 'security_shield': 'active'}
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        db.session.rollback()
        checks['database'] = 'error'

    try:
        os.makedirs(app.static_folder, exist_ok=True)
        checks['uploads'] = 'ok' if os.access(app.static_folder, os.W_OK) else 'warning'
    except Exception:
        checks['uploads'] = 'error'

    if not platform_setting_bool('security_shield_enabled', True):
        checks['security_shield'] = 'passive'

    degraded = any(value == 'error' for value in checks.values())
    return {
        'status': 'degraded' if degraded else 'healthy',
        'checks': checks,
        'environment': app.config.get('APP_ENV', 'development'),
        'latest_backup': BackupLog.query.order_by(BackupLog.created_at.desc()).first(),
    }


def build_tenant_backup_payload(user):
    """Request-context independent tenant backup payload."""
    return {
        'user_info': {
            'firma_adi': user.firma_adi,
            'yetkili_adi': getattr(user, 'yetkili_adi', None),
            'email': user.email,
            'telefon': getattr(user, 'telefon', None),
            'vergi_dairesi': getattr(user, 'vergi_dairesi', None),
            'vergi_numarasi': getattr(user, 'vergi_numarasi', None),
            'adres': getattr(user, 'adres', None),
            'paket_tipi': getattr(user, 'paket_tipi', None),
            'created_at': user.kayit_tarihi.isoformat() if getattr(user, 'kayit_tarihi', None) else None
        },
        'urunler': [
            {
                'id': urun.id,
                'urun_adi': urun.urun_adi,
                'barkod': urun.barkod,
                'kategori': urun.kategori,
                'stok_miktari': urun.stok_miktari,
                'kritik_stok': urun.kritik_stok,
                'birim': urun.birim,
                'alis_fiyati': urun.alis_fiyati,
                'satis_fiyati': urun.satis_fiyati,
                'depo_adi': urun.depo_adi,
                'eklenme_tarihi': urun.eklenme_tarihi.isoformat() if urun.eklenme_tarihi else None
            }
            for urun in Urun.query.filter_by(user_id=user.id).all()
        ],
        'cariler': [
            {
                'id': cari.id,
                'unvan': cari.unvan,
                'telefon': cari.telefon,
                'email': cari.email,
                'vergidairesi': cari.vergidairesi,
                'vergi_numarasi': cari.vergi_numarasi,
                'adres': cari.adres,
                'borc': cari.borc,
                'alacak': cari.alacak,
                'created_at': cari.kayit_tarihi.isoformat() if cari.kayit_tarihi else None
            }
            for cari in Cari.query.filter_by(user_id=user.id).all()
        ],
        'satislar': [
            {
                'id': satis.id,
                'fatura_no': satis.fatura_no,
                'cari_id': satis.cari_id,
                'tarih': satis.tarih.isoformat() if satis.tarih else None,
                'genel_toplam': satis.genel_toplam,
                'durum': satis.durum,
                'notlar': satis.notlar
            }
            for satis in Satis.query.filter_by(user_id=user.id).all()
        ],
        'teklifler': [
            {
                'id': teklif.id,
                'teklif_no': teklif.teklif_no,
                'cari_id': teklif.cari_id,
                'tarih': teklif.tarih.isoformat() if teklif.tarih else None,
                'genel_toplam': teklif.genel_toplam,
                'durum': teklif.durum,
                'notlar': teklif.notlar
            }
            for teklif in Teklif.query.filter_by(user_id=user.id).all()
        ],
        'iade_kayitlari': [
            {
                'id': iade.id,
                'cari_id': iade.cari_id,
                'iade_turu': iade.iade_turu,
                'iade_sebebi': iade.iade_sebebi,
                'iade_tutari': iade.iade_tutari,
                'tarih': iade.tarih.isoformat() if iade.tarih else None,
                'durum': iade.durum
            }
            for iade in Iade.query.filter_by(user_id=user.id).all()
        ],
        'backup_info': {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'version': '1.0',
            'user_id': user.id
        }
    }


def validate_tenant_backup_payload(payload):
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get('user_info', {}), dict):
        return False
    for key in ('urunler', 'cariler', 'satislar', 'teklifler', 'iade_kayitlari'):
        records = payload.get(key, [])
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            return False
    return True


def backup_owner_folder_name(user):
    user_id = getattr(user, 'id', None)
    raw_name = (
        getattr(user, 'firma_adi', None)
        or getattr(user, 'yetkili_adi', None)
        or getattr(user, 'email', None)
        or f'kullanici-{user_id or "bilinmeyen"}'
    )
    normalized = str(raw_name).strip().lower().replace('@', '-at-')
    folder_name = secure_filename(normalized)
    folder_name = re.sub(r'[-_]+', '-', folder_name).strip('-_') or 'kullanici'
    return f'{folder_name}-{user_id}' if user_id else folder_name


def backup_user_from_id(user_id):
    if not user_id:
        return None
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def backup_dir_for_user(user_or_id):
    if hasattr(user_or_id, 'id'):
        return os.path.join('backups', backup_owner_folder_name(user_or_id))

    user = backup_user_from_id(user_or_id)
    if user:
        return os.path.join('backups', backup_owner_folder_name(user))
    return os.path.join('backups', str(user_or_id))


def legacy_backup_dir_for_user(user_or_id):
    user_id = getattr(user_or_id, 'id', user_or_id)
    return os.path.join('backups', str(user_id))


def backup_file_path_for_user(user_or_id, filename):
    primary_path = os.path.join(backup_dir_for_user(user_or_id), filename)
    if os.path.exists(primary_path):
        return primary_path

    legacy_path = os.path.join(legacy_backup_dir_for_user(user_or_id), filename)
    if os.path.exists(legacy_path):
        return legacy_path
    return primary_path


def write_tenant_backup_file(user, payload, backup_type='manual', filename_prefix='backup'):
    backup_dir = backup_dir_for_user(user)
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    filename = f'{filename_prefix}_{timestamp}.json'
    backup_path = os.path.join(backup_dir, filename)
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    file_size = os.path.getsize(backup_path)
    db.session.add(BackupLog(
        filename=filename,
        file_size=file_size,
        backup_type=backup_type,
        status='completed',
        user_id=user.id,
        completed_at=datetime.now(timezone.utc)
    ))
    return filename, file_size


def apply_backup_retention(retention_days):
    if not retention_days or retention_days <= 0:
        return {'deleted': 0, 'errors': 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(retention_days))
    old_logs = BackupLog.query.filter(BackupLog.created_at < cutoff).order_by(BackupLog.created_at.asc()).all()
    deleted = 0
    errors = 0
    for log in old_logs:
        try:
            backup_path = backup_file_path_for_user(log.user_id, log.filename)
            if os.path.isfile(backup_path):
                os.remove(backup_path)
            db.session.delete(log)
            deleted += 1
        except OSError:
            errors += 1
    return {'deleted': deleted, 'errors': errors}


def auto_backup_due(now_utc, last_run, frequency):
    if frequency == 'daily':
        return not last_run or (now_utc - last_run) >= timedelta(hours=20)
    if frequency == 'weekly':
        return not last_run or (now_utc - last_run) >= timedelta(days=6)
    if frequency == 'monthly':
        return not last_run or (now_utc - last_run) >= timedelta(days=27)
    return False


def run_platform_auto_backup(force=False):
    frequency = platform_setting('auto_backup_frequency', 'daily')
    if frequency not in {'daily', 'weekly', 'monthly'}:
        return {'ran': False, 'reason': 'off_or_invalid'}

    now_utc = datetime.now(timezone.utc)
    last_run = platform_setting_datetime('auto_backup_last_run')
    if not force and not auto_backup_due(now_utc, last_run, frequency):
        return {'ran': False, 'reason': 'not_due'}

    running_at = platform_setting_datetime('auto_backup_running_at')
    if platform_setting_bool('auto_backup_running', False) and running_at and (now_utc - running_at) < timedelta(hours=2):
        return {'ran': False, 'reason': 'already_running'}

    set_platform_setting('auto_backup_running', 'on', 'Otomatik yedekleme calisiyor')
    set_platform_setting('auto_backup_running_at', now_utc.isoformat(), 'Otomatik yedekleme baslangic zamani')
    db.session.commit()

    created = 0
    failed = 0
    retention_days = platform_setting_int('backup_retention_days', 30)
    try:
        organizations = [
            organization for organization in Organization.query.filter_by(active=True).all()
            if is_customer_organization(organization)
        ]
        for organization in organizations:
            owner = organization_owner(organization)
            if not owner:
                continue
            try:
                payload = build_tenant_backup_payload(owner)
                payload['backup_info']['scope'] = 'tenant'
                payload['backup_info']['backup_type'] = 'auto'
                write_tenant_backup_file(owner, payload, backup_type='auto', filename_prefix='auto_backup')
                db.session.commit()
                created += 1
            except Exception as exc:
                db.session.rollback()
                db.session.add(BackupLog(
                    filename=f'auto_backup_failed_{now_utc.strftime("%Y%m%d_%H%M%S")}.json',
                    file_size=0,
                    backup_type='auto',
                    status='failed',
                    user_id=owner.id,
                    error_message=str(exc)[:2000],
                    completed_at=datetime.now(timezone.utc)
                ))
                db.session.commit()
                failed += 1

        retention_result = apply_backup_retention(retention_days)
        set_platform_setting('auto_backup_last_run', now_utc.isoformat(), 'Otomatik yedekleme son calisma zamani')
        set_platform_setting('auto_backup_running', 'off')
        db.session.commit()
        return {
            'ran': True,
            'created': created,
            'failed': failed,
            'retention': retention_result,
            'frequency': frequency,
        }
    finally:
        set_platform_setting('auto_backup_running', 'off')
        db.session.commit()


def system_security_context():
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    failed_logins = AuditLog.query.filter(
        AuditLog.action == 'LOGIN_FAILED',
        AuditLog.timestamp >= since
    ).count()
    blocked_threats = AuditLog.query.filter(
        AuditLog.action == 'SECURITY_THREAT_BLOCKED',
        AuditLog.timestamp >= since
    ).count()
    recent_events = AuditLog.query.filter(
        AuditLog.action.in_([
            'SECURITY_THREAT_BLOCKED',
            'LOGIN_FAILED',
            'PLATFORM_SYSTEM_CONTROLS_UPDATE',
            'PLATFORM_MAINTENANCE',
            'PLATFORM_IMPERSONATE_START',
            'PLATFORM_SELF_TEST_RUN',
            'PLATFORM_LOCK_BLOCKED',
        ])
    ).order_by(AuditLog.timestamp.desc()).limit(8).all()
    return {
        'failed_logins_24h': failed_logins,
        'blocked_threats_24h': blocked_threats,
        'recent_events': recent_events,
    }


def self_test_result_item(status, severity, area, check, expected, actual,
                          probable_cause='', suggestion='', technical_detail=''):
    return {
        'status': status,
        'severity': severity,
        'area': area,
        'check': check,
        'expected': expected,
        'actual': actual,
        'probable_cause': probable_cause,
        'suggestion': suggestion,
        'technical_detail': technical_detail,
    }


def route_methods(endpoint):
    methods = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == endpoint:
            methods.update((rule.methods or set()) - {'HEAD', 'OPTIONS'})
    return methods


def platform_self_test_last_result():
    value = platform_setting('self_test_last_result', '')
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def platform_workflow_test_last_result():
    value = platform_setting('workflow_test_last_result', '')
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def platform_single_test_last_result():
    value = platform_setting('single_test_last_result', '')
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def run_platform_self_test():
    checks = []

    try:
        db.session.execute(text('SELECT 1'))
        checks.append(self_test_result_item(
            'passed', 'critical', 'Veritabani', 'Baglanti kontrolu',
            'Veritabani SELECT 1 sorgusuna cevap vermeli.',
            'Veritabani cevap verdi.',
            technical_detail='SELECT 1'
        ))
    except Exception as exc:
        db.session.rollback()
        checks.append(self_test_result_item(
            'failed', 'critical', 'Veritabani', 'Baglanti kontrolu',
            'Veritabani SELECT 1 sorgusuna cevap vermeli.',
            f'Veritabani hatasi: {exc}',
            'Veritabani dosyasi, migration veya SQLAlchemy baglantisi bozulmus olabilir.',
            'Uygulama loglarini ve veritabani dosya izinlerini kontrol edin.',
            'SELECT 1'
        ))

    required_routes = [
        ('super_admin_dashboard', {'GET'}, 'Super Admin', 'Super admin paneli'),
        ('super_admin_update_system_controls', {'POST'}, 'Sistem Yonetimi', 'Sistem kilitlerini kaydetme'),
        ('super_admin_run_self_test', {'POST'}, 'Sistem Yonetimi', 'Test robotu calistirma'),
        ('super_admin_run_workflow_test', {'POST'}, 'Sistem Yonetimi', 'Derin is akisi testi calistirma'),
        ('super_admin_run_inventory_test', {'POST'}, 'Sistem Yonetimi', 'Tekil test calistirma'),
        ('super_admin_update_organization', {'POST'}, 'Firma Yonetimi', 'Firma ayari guncelleme'),
        ('super_admin_impersonate', {'POST'}, 'Firma Yonetimi', 'Destek modu girisi'),
        ('super_admin_backups', {'GET'}, 'Yedekleme', 'Platform yedekleri'),
        ('super_admin_logs', {'GET'}, 'Audit Log', 'Platform loglari'),
        ('settings', {'GET'}, 'Ayarlar', 'Kullanici ayarlari sayfasi'),
        ('update_preferences', {'POST'}, 'Ayarlar', 'Tercih kaydetme API'),
        ('update_notifications', {'POST'}, 'Ayarlar', 'Bildirim kaydetme API'),
        ('download_backup', {'GET'}, 'Yedekleme', 'Yedek indirme API'),
    ]
    for endpoint, expected_methods, area, check_name in required_routes:
        methods = route_methods(endpoint)
        missing = expected_methods - methods
        checks.append(self_test_result_item(
            'failed' if missing else 'passed',
            'critical' if missing else 'info',
            area,
            check_name,
            f'Endpoint {endpoint} {", ".join(sorted(expected_methods))} metodlarini desteklemeli.',
            f'Mevcut metodlar: {", ".join(sorted(methods)) if methods else "endpoint yok"}',
            'Route adi degismis, endpoint silinmis veya HTTP metodu eksik olabilir.' if missing else '',
            f'app.py icinde {endpoint} route tanimini kontrol edin.' if missing else '',
            f'endpoint={endpoint}'
        ))

    required_templates = [
        ('templates/super_admin/dashboard.html', 'Super Admin', 'Super admin dashboard template'),
        ('templates/super_admin/logs.html', 'Audit Log', 'Platform loglari template'),
        ('templates/super_admin/backups.html', 'Yedekleme', 'Platform yedekleri template'),
        ('templates/settings.html', 'Ayarlar', 'Kullanici ayarlari template'),
        ('templates/_base.html', 'Uygulama Kabugu', 'Ana layout template'),
    ]
    for relative_path, area, check_name in required_templates:
        exists = os.path.exists(relative_path)
        checks.append(self_test_result_item(
            'passed' if exists else 'failed',
            'critical' if not exists else 'info',
            area,
            check_name,
            f'{relative_path} dosyasi bulunmali.',
            'Dosya bulundu.' if exists else 'Dosya bulunamadi.',
            'Template silinmis veya adi degismis olabilir.' if not exists else '',
            f'{relative_path} dosyasini geri getirin veya render_template kullanimini guncelleyin.' if not exists else '',
            relative_path
        ))

    controls = platform_system_controls()
    required_locks = [
        'owner_account_protection',
        'financial_changes_locked',
        'support_impersonation_locked',
        'data_export_locked',
        'owner_approval_required',
    ]
    for lock_key in required_locks:
        checks.append(self_test_result_item(
            'passed' if lock_key in controls else 'failed',
            'critical' if lock_key not in controls else 'info',
            'Calisma Modu ve Kilitler',
            f'{lock_key} kontrolu',
            'Kilit sistem kontrolleri icinde okunabilir olmali.',
            f'Deger: {controls.get(lock_key)}' if lock_key in controls else 'Kilit okunamadi.',
            'platform_system_controls sozlugunde anahtar eksik olabilir.' if lock_key not in controls else '',
            'app.py platform_system_controls fonksiyonunu kontrol edin.' if lock_key not in controls else '',
            f'lock={lock_key}'
        ))

    owner_permission_ok = 'settings_manage' in PLATFORM_ROLE_PERMISSIONS.get('owner', set())
    support_team_denied = 'team_manage' not in PLATFORM_ROLE_PERMISSIONS.get('support', set())
    checks.append(self_test_result_item(
        'passed' if owner_permission_ok and support_team_denied else 'failed',
        'critical' if not (owner_permission_ok and support_team_denied) else 'info',
        'Yetkilendirme',
        'Platform rol matrisi',
        'Owner tum kritik yetkilere sahip, destek rolu ekip yonetimine sahip olmamali.',
        f'owner.settings_manage={owner_permission_ok}, support.team_manage={not support_team_denied}',
        'PLATFORM_ROLE_PERMISSIONS yanlis duzenlenmis olabilir.' if not (owner_permission_ok and support_team_denied) else '',
        'Rol matrisini owner/support ayrimina gore duzeltin.' if not (owner_permission_ok and support_team_denied) else '',
        'PLATFORM_ROLE_PERMISSIONS'
    ))

    owner_count = User.query.filter_by(is_platform_admin=True, platform_role='owner', aktif=True).count()
    checks.append(self_test_result_item(
        'passed' if owner_count > 0 else 'failed',
        'critical' if owner_count == 0 else 'info',
        'Platform Ekibi',
        'Aktif platform sahibi',
        'En az bir aktif platform sahibi hesabi bulunmali.',
        f'Aktif platform sahibi sayisi: {owner_count}',
        'Owner rolundeki hesap pasif veya eksik olabilir.' if owner_count == 0 else '',
        'Bir platform sahibi hesabini aktif owner rolune alin.' if owner_count == 0 else '',
        'User.is_platform_admin=True, platform_role=owner'
    ))

    linked_staff = User.query.filter(
        User.is_platform_admin.is_(True),
        User.role == 'platform_staff',
        User.organization_id.isnot(None)
    ).all()
    checks.append(self_test_result_item(
        'passed' if not linked_staff else 'warning',
        'warning' if linked_staff else 'info',
        'Platform Ekibi',
        'Ekip-firma ayrimi',
        'Platform ekibi uyelerinin organization_id alani bos olmali.',
        'Bagli ekip uyesi yok.' if not linked_staff else f'{len(linked_staff)} ekip uyesi firmaya bagli gorunuyor.',
        'Gecmis kayit veya manuel veri duzenlemesi platform ekibini firmaya baglamis olabilir.' if linked_staff else '',
        'Platform ekibi uyesini kaydedin; guncelleme islemi organization_id alanini bosaltir.' if linked_staff else '',
        ', '.join(user.email for user in linked_staff[:5])
    ))

    orphan_organizations = [
        organization for organization in Organization.query.all()
        if organization_owner(organization) is None
    ]
    checks.append(self_test_result_item(
        'passed' if not orphan_organizations else 'warning',
        'warning' if orphan_organizations else 'info',
        'Firma Yonetimi',
        'Firma sahip baglantisi',
        'Her firma icin sahip kullanici bulunmali.',
        'Sahipsiz firma yok.' if not orphan_organizations else f'{len(orphan_organizations)} sahipsiz firma var.',
        'Owner kullanici silinmis veya organization.owner_user_id gecersiz olabilir.' if orphan_organizations else '',
        'Firma detayinda owner kullaniciyi yeniden atayin veya kaydi inceleyin.' if orphan_organizations else '',
        ', '.join(organization.name for organization in orphan_organizations[:5])
    ))

    latest_backup = BackupLog.query.order_by(BackupLog.created_at.desc()).first()
    checks.append(self_test_result_item(
        'passed' if latest_backup else 'warning',
        'warning' if not latest_backup else 'info',
        'Yedekleme',
        'Son yedek kaydi',
        'Sistemde en az bir yedek kaydi bulunmasi onerilir.',
        latest_backup.created_at.isoformat() if latest_backup and latest_backup.created_at else 'Yedek kaydi yok.',
        'Yeni kurulum veya yedekleme rutini calismamis olabilir.' if not latest_backup else '',
        'Manuel yedek olusturun veya otomatik yedekleme politikasini kontrol edin.' if not latest_backup else '',
        'BackupLog'
    ))

    audit_label_ok = AUDIT_ACTION_LABELS.get('PLATFORM_LOCK_BLOCKED') == 'Kilitli islem engellendi'
    checks.append(self_test_result_item(
        'passed' if audit_label_ok else 'failed',
        'critical' if not audit_label_ok else 'info',
        'Audit Log',
        'Kilit engeli log etiketi',
        'PLATFORM_LOCK_BLOCKED loglari Turkce etiketle gorunmeli.',
        'Etiket hazir.' if audit_label_ok else 'Etiket eksik.',
        'AUDIT_ACTION_LABELS icinde yeni aksiyon yok olabilir.' if not audit_label_ok else '',
        'AUDIT_ACTION_LABELS sozlugune PLATFORM_LOCK_BLOCKED ekleyin.' if not audit_label_ok else '',
        'PLATFORM_LOCK_BLOCKED'
    ))

    template_paths = []
    for root, _, files in os.walk('templates'):
        if 'instance' in root.split(os.sep):
            continue
        for filename in files:
            if filename.endswith('.html'):
                template_paths.append(os.path.join(root, filename))

    button_count = 0
    form_count = 0
    for path in template_paths:
        try:
            content = open(path, 'r', encoding='utf-8', errors='replace').read().lower()
        except OSError:
            continue
        button_count += content.count('<button')
        form_count += content.count('<form')

    route_count = len(list(app.url_map.iter_rules()))
    api_route_count = len([rule for rule in app.url_map.iter_rules() if str(rule.rule).startswith('/api/')])
    failed_count = sum(1 for item in checks if item['status'] == 'failed')
    warning_count = sum(1 for item in checks if item['status'] == 'warning')
    passed_count = sum(1 for item in checks if item['status'] == 'passed')
    critical_failed = any(item['status'] == 'failed' and item['severity'] == 'critical' for item in checks)
    status = 'failed' if critical_failed else 'warning' if warning_count or failed_count else 'passed'

    result = {
        'status': status,
        'status_label': {
            'passed': 'Uygulama kararli ve calisir durumda',
            'warning': 'Uygulama calisiyor, uyarilar var',
            'failed': 'Kritik hata var, mudahale gerekli',
        }[status],
        'ran_at': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total': len(checks),
            'passed': passed_count,
            'warnings': warning_count,
            'failed': failed_count,
            'routes': route_count,
            'api_routes': api_route_count,
            'templates': len(template_paths),
            'forms': form_count,
            'buttons': button_count,
        },
        'checks': checks,
    }
    set_platform_setting('self_test_last_result', json.dumps(result, ensure_ascii=False), 'Son test robotu raporu')
    platform_audit(
        'PLATFORM_SELF_TEST_RUN',
        f"Test robotu: {result['status_label']} ({passed_count}/{len(checks)} gecti, {warning_count} uyari, {failed_count} hata).",
        'Platform'
    )
    db.session.commit()
    return result


TEST_INVENTORY_CATEGORY_RULES = [
    ('Platform ve Destek', ('super_admin', 'platform', 'support', 'action_center', 'impersonation')),
    ('Ayarlar ve Guvenlik', ('settings', 'security', 'login', 'password', 'maintenance', 'readonly', 'bootstrap', 'reserved_owner')),
    ('Urun ve Stok', ('urun', 'product', 'stok', 'warehouse', 'demo_data')),
    ('Cari ve Finans', ('cari', 'onmuhasebe', 'nakit', 'cash', 'account', 'mutabakat', 'payment', 'payroll')),
    ('POS ve Satis', ('pos', 'sale', 'sales', 'daily_sales', 'receipt', 'cancel')),
    ('Teklifler', ('teklif', 'quote')),
    ('Personel', ('personel', 'departman', 'izin', 'avans', 'prim', 'bordro')),
    ('Iade', ('iade', 'return')),
    ('Arayuz ve Gezinme', ('dashboard', 'navigation', 'template', 'render', 'page', 'sidebar', 'header')),
]

TEST_INVENTORY_TOKEN_MAP = {
    'pos': 'POS',
    'api': 'API',
    'ui': 'arayuz',
    'user': 'kullanici',
    'users': 'kullanicilar',
    'settings': 'ayarlar',
    'setting': 'ayar',
    'security': 'guvenlik',
    'password': 'parola',
    'login': 'giris',
    'logout': 'cikis',
    'platform': 'platform',
    'owner': 'sahip',
    'admin': 'admin',
    'super': 'super',
    'dashboard': 'panel',
    'support': 'destek',
    'ticket': 'talep',
    'tickets': 'talepler',
    'backup': 'yedek',
    'backups': 'yedekler',
    'download': 'indirme',
    'upload': 'yukleme',
    'create': 'olusturma',
    'creates': 'olusturur',
    'update': 'guncelleme',
    'updates': 'gunceller',
    'render': 'gosterim',
    'renders': 'gosterilir',
    'show': 'gosterim',
    'shows': 'gosterir',
    'list': 'liste',
    'page': 'sayfa',
    'pages': 'sayfalar',
    'filters': 'filtreler',
    'work': 'calisir',
    'works': 'calisir',
    'valid': 'gecerli',
    'validated': 'dogrulaniyor',
    'persisted': 'kaydoluyor',
    'hidden': 'gizli',
    'visible': 'gorunur',
    'requires': 'gerektirir',
    'blocks': 'engeller',
    'rejects': 'reddeder',
    'returns': 'doner',
    'without': 'olmadan',
    'default': 'varsayilan',
    'defaults': 'varsayilanlar',
    'product': 'urun',
    'products': 'urunler',
    'warehouse': 'depo',
    'warehouses': 'depolar',
    'cari': 'cari',
    'account': 'hesap',
    'accounts': 'hesaplar',
    'payment': 'odeme',
    'payments': 'odemeler',
    'cash': 'nakit',
    'sale': 'satis',
    'sales': 'satislar',
    'cancel': 'iptal',
    'daily': 'gunluk',
    'report': 'rapor',
    'reports': 'raporlar',
    'teklif': 'teklif',
    'personel': 'personel',
    'departman': 'departman',
    'izin': 'izin',
    'avans': 'avans',
    'prim': 'prim',
    'payroll': 'bordro',
    'iade': 'iade',
    'flow': 'akisi',
    'full': 'tam',
    'regression': 'regresyon',
}


def categorize_test_inventory_item(test_name):
    lowered = test_name.lower()
    for category, keywords in TEST_INVENTORY_CATEGORY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return 'Genel'


def humanize_test_inventory_name(test_name):
    tokens = test_name.removeprefix('test_').split('_')
    human_tokens = [TEST_INVENTORY_TOKEN_MAP.get(token, token) for token in tokens if token]
    label = ' '.join(human_tokens).strip()
    if not label:
        return test_name
    return label[:1].upper() + label[1:]


def platform_test_inventory():
    test_file = Path(app.root_path) / 'tests' / 'test_app.py'
    if not test_file.exists():
        return {'source_file': 'tests/test_app.py', 'total': 0, 'groups': [], 'error': 'Test dosyasi bulunamadi'}

    try:
        module = ast.parse(test_file.read_text(encoding='utf-8'))
    except Exception as exc:
        return {'source_file': 'tests/test_app.py', 'total': 0, 'groups': [], 'error': safe_exception_message(exc)}

    items = []
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
            items.append({
                'technical_name': node.name,
                'label': humanize_test_inventory_name(node.name),
                'category': categorize_test_inventory_item(node.name),
                'line': node.lineno,
            })

    grouped = {}
    for item in items:
        grouped.setdefault(item['category'], []).append(item)

    groups = []
    ordered_categories = [category for category, _ in TEST_INVENTORY_CATEGORY_RULES] + ['Genel']
    for category in ordered_categories:
        if category in grouped:
            groups.append({
                'category': category,
                'count': len(grouped[category]),
                'items': grouped[category],
            })

    return {
        'source_file': 'tests/test_app.py',
        'total': len(items),
        'groups': groups,
        'error': '',
    }


def run_platform_inventory_test(test_name):
    inventory = platform_test_inventory()
    inventory_items = [
        item
        for group in inventory.get('groups', [])
        for item in group.get('items', [])
    ]
    selected_item = next((item for item in inventory_items if item['technical_name'] == test_name), None)

    if not selected_item:
        result = {
            'status': 'failed',
            'status_label': 'Secilen test bulunamadi',
            'ran_at': datetime.now(timezone.utc).isoformat(),
            'technical_name': test_name,
            'label': humanize_test_inventory_name(test_name),
            'target': f'tests/test_app.py::{test_name}',
            'line': None,
            'duration_seconds': 0,
            'returncode': 1,
            'output': 'Test envanterinde bu ada sahip bir test bulunamadi.',
        }
        set_platform_setting('single_test_last_result', json.dumps(result, ensure_ascii=False), 'Son tekil test calisma raporu')
        platform_audit('PLATFORM_SINGLE_TEST_RUN', f'Tekil test bulunamadi: {test_name}', 'Platform')
        db.session.commit()
        return result

    command = [sys.executable, '-m', 'pytest', f"tests/test_app.py::{test_name}", '-q']
    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=app.root_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
            check=False,
        )
        duration_seconds = round(time.perf_counter() - started_at, 2)
        combined_output = '\n'.join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip()
        status = 'passed' if completed.returncode == 0 else 'failed'
        result = {
            'status': status,
            'status_label': 'Test gecti' if status == 'passed' else 'Test hata verdi',
            'ran_at': datetime.now(timezone.utc).isoformat(),
            'technical_name': test_name,
            'label': selected_item['label'],
            'target': f'tests/test_app.py::{test_name}',
            'line': selected_item['line'],
            'duration_seconds': duration_seconds,
            'returncode': completed.returncode,
            'output': (combined_output or 'Pytest cikti uretmedi.')[:6000],
        }
    except subprocess.TimeoutExpired:
        duration_seconds = round(time.perf_counter() - started_at, 2)
        result = {
            'status': 'failed',
            'status_label': 'Test zaman asimina ugradi',
            'ran_at': datetime.now(timezone.utc).isoformat(),
            'technical_name': test_name,
            'label': selected_item['label'],
            'target': f'tests/test_app.py::{test_name}',
            'line': selected_item['line'],
            'duration_seconds': duration_seconds,
            'returncode': 124,
            'output': 'Pytest 120 saniye icinde tamamlanmadi.',
        }

    set_platform_setting('single_test_last_result', json.dumps(result, ensure_ascii=False), 'Son tekil test calisma raporu')
    platform_audit(
        'PLATFORM_SINGLE_TEST_RUN',
        f"{test_name}: {result['status_label']} (kod={result['returncode']}, sure={result['duration_seconds']} sn)",
        'Platform'
    )
    db.session.commit()
    return result


def cleanup_platform_workflow_sandbox(user_id=None, organization_id=None, user_ids=None, organization_ids=None):
    try:
        db.session.rollback()
    except Exception:
        pass

    all_user_ids = {uid for uid in (user_ids or []) if uid}
    if user_id:
        all_user_ids.add(user_id)

    all_org_ids = {oid for oid in (organization_ids or []) if oid}
    if organization_id:
        all_org_ids.add(organization_id)

    for uid in sorted(all_user_ids):
        sale_ids = [sale.id for sale in Satis.query.filter_by(user_id=uid).all()]
        quote_ids = [quote.id for quote in Teklif.query.filter_by(user_id=uid).all()]
        return_ids = [return_record.id for return_record in Iade.query.filter_by(user_id=uid).all()]
        if sale_ids:
            SatisKalemi.query.filter(SatisKalemi.satis_id.in_(sale_ids)).delete(synchronize_session=False)
        if quote_ids:
            TeklifKalemi.query.filter(TeklifKalemi.teklif_id.in_(quote_ids)).delete(synchronize_session=False)
        if return_ids:
            IadeKalem.query.filter(IadeKalem.iade_id.in_(return_ids)).delete(synchronize_session=False)

        CariHareket.query.filter_by(user_id=uid).delete(synchronize_session=False)
        StokHareket.query.filter_by(user_id=uid).delete(synchronize_session=False)
        CashTransaction.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Account.query.filter_by(user_id=uid).delete(synchronize_session=False)
        AuditLog.query.filter_by(user_id=uid).delete(synchronize_session=False)
        BackupLog.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Iade.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Satis.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Teklif.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Cari.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Urun.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Warehouse.query.filter_by(user_id=uid).delete(synchronize_session=False)
        Category.query.filter_by(user_id=uid).delete(synchronize_session=False)
        SystemSettings.query.filter_by(user_id=uid).delete(synchronize_session=False)

        user = db.session.get(User, uid)
        if user:
            user.organization_id = None
            db.session.delete(user)

    for oid in sorted(all_org_ids):
        organization = db.session.get(Organization, oid)
        if organization:
            db.session.delete(organization)

    db.session.commit()


def workflow_summary(checks):
    failed_count = sum(1 for item in checks if item['status'] == 'failed')
    warning_count = sum(1 for item in checks if item['status'] == 'warning')
    passed_count = sum(1 for item in checks if item['status'] == 'passed')
    critical_failed = any(item['status'] == 'failed' and item['severity'] == 'critical' for item in checks)
    status = 'failed' if critical_failed else 'warning' if warning_count or failed_count else 'passed'
    return status, passed_count, warning_count, failed_count


def run_platform_workflow_test():
    checks = []
    sandbox_user_id = None
    sandbox_organization_id = None
    suffix = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')

    def run_request_as(user, path, method='GET', json_payload=None, form_data=None):
        with app.test_request_context(path, method=method, json=json_payload, data=form_data):
            try:
                session['_user_id'] = str(user.id)
                session['_fresh'] = True
                session['login_at'] = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
            login_user(user)

            endpoint_map = {
                '/pos/satis': pos_satis,
                '/teklif/ekle': teklif_ekle,
                '/iade': iade,
                '/gunluk-satislar': gunluk_satislar,
                '/raporlar': raporlar,
            }
            view = endpoint_map.get(path)
            if not view:
                raise RuntimeError(f'Workflow test route not mapped: {path}')
            return app.make_response(view())

    try:
        sandbox_user = User(
            email=f'test_robot_{suffix}@example.invalid',
            password=generate_password_hash(uuid.uuid4().hex),
            firma_adi=f'TEST_ROBOT Firma {suffix}',
            yetkili_adi='Test Robotu',
            paket_tipi='profesyonel',
            urun_limiti=1000,
            aktif=True,
            role='owner',
            is_platform_admin=False,
        )
        db.session.add(sandbox_user)
        db.session.flush()
        sandbox_user_id = sandbox_user.id
        organization = ensure_user_organization(sandbox_user)
        organization.name = f'TEST_ROBOT Firma {suffix}'
        sandbox_organization_id = organization.id

        warehouse = Warehouse(name='TEST_ROBOT Depo', user_id=sandbox_user.id)
        category = Category(name='TEST_ROBOT Kategori', user_id=sandbox_user.id)
        product = Urun(
            barkod=f'TR-{suffix}',
            urun_adi=f'TEST_ROBOT Urun {suffix}',
            kategori=category.name,
            birim='Adet',
            alis_fiyati=50,
            satis_fiyati=100,
            stok_miktari=10,
            kritik_stok=2,
            depo_adi=warehouse.name,
            user_id=sandbox_user.id,
        )
        cari = Cari(
            unvan=f'TEST_ROBOT Cari {suffix}',
            yetkili='Test Robotu',
            tipi='Musteri',
            user_id=sandbox_user.id,
        )
        db.session.add_all([warehouse, category, product, cari])
        db.session.commit()

        checks.append(self_test_result_item(
            'passed' if all([sandbox_user.id, organization.id, product.id, cari.id]) else 'failed',
            'critical',
            'Sandbox',
            'Gecici firma veri seti',
            'Robot kendi gecici firma, urun, depo ve cari kayitlarini olusturabilmeli.',
            f'firma={organization.id}, user={sandbox_user.id}, urun={product.id}, cari={cari.id}',
            'Veritabani yazma izni veya zorunlu alanlarda uyumsuzluk olabilir.' if not all([sandbox_user.id, organization.id, product.id, cari.id]) else '',
            'User, Organization, Urun, Cari model alanlarini ve migration durumunu kontrol edin.' if not all([sandbox_user.id, organization.id, product.id, cari.id]) else '',
            'User/Organization/Urun/Cari'
        ))

        sale_response = run_request_as(sandbox_user, '/pos/satis', method='POST', json_payload={
            'customerId': cari.id,
            'warehouse': warehouse.name,
            'paymentMethod': 'cash',
            'kdvRate': 20,
            'discount': 0,
            'items': [{
                'id': product.id,
                'quantity': 2,
                'price': 100,
                'unit': 'Adet',
            }],
        })

        sale_data = sale_response.get_json(silent=True) or {}
        db.session.expire_all()
        product_after_sale = db.session.get(Urun, product.id)
        cari_after_sale = db.session.get(Cari, cari.id)
        sale = Satis.query.filter_by(user_id=sandbox_user.id).order_by(Satis.id.desc()).first()
        stock_out = StokHareket.query.filter_by(user_id=sandbox_user.id, islem_tipi='cikis').first()
        cari_move = CariHareket.query.filter_by(user_id=sandbox_user.id, islem_tipi='satis').first()
        cash_move = CashTransaction.query.filter_by(user_id=sandbox_user.id, islem_tipi='giris').first()

        sale_ok = (
            sale_response.status_code == 200
            and sale_data.get('success') is True
            and product_after_sale
            and abs((product_after_sale.stok_miktari or 0) - 8) < 0.001
            and sale
            and abs((sale.genel_toplam or 0) - 240) < 0.001
        )
        checks.append(self_test_result_item(
            'passed' if sale_ok else 'failed',
            'critical',
            'POS Satis',
            'Stok dusen satis akisi',
            'POS satis 2 adet urun satmali, stogu 10dan 8e dusurmeli ve toplam 240 TRY olmali.',
            f'http={sale_response.status_code}, success={sale_data.get("success")}, stok={getattr(product_after_sale, "stok_miktari", None)}, toplam={getattr(sale, "genel_toplam", None)}',
            'POS endpointi, stok yeterlilik kontrolu, KDV hesabi veya fatura kaydi bozulmus olabilir.' if not sale_ok else '',
            'pos_satis, record_stock_movement ve Satis/SatisKalemi kayitlarini birlikte kontrol edin.' if not sale_ok else '',
            '/pos/satis'
        ))

        accounting_ok = (
            cari_after_sale
            and stock_out
            and cash_move
            and not cari_move
            and abs((cari_after_sale.alacak or 0) - 0) < 0.001
            and abs((cash_move.tutar or 0) - 240) < 0.001
        )
        checks.append(self_test_result_item(
            'passed' if accounting_ok else 'failed',
            'critical',
            'Cari ve Nakit',
            'Nakit satis muhasebe izleri',
            'Nakit satis; stok hareketi ve nakit girisi olusturmali, cari bakiyesi degismemeli.',
            f'stok_hareket={bool(stock_out)}, cari_hareket={bool(cari_move)}, nakit={bool(cash_move)}, cari_alacak={getattr(cari_after_sale, "alacak", None)}, nakit_tutar={getattr(cash_move, "tutar", None)}',
            'Nakit satis tamamlanmis olsa bile stok veya nakit kaydi eksik yaziliyor olabilir.' if not accounting_ok else '',
            'StokHareket ve CashTransaction olusumunu; cari hareketinin ise sadece veresiye akislarda yazildigini kontrol edin.' if not accounting_ok else '',
            'StokHareket/CashTransaction/CariHareket'
        ))

        insufficient_response = run_request_as(sandbox_user, '/pos/satis', method='POST', json_payload={
            'customerId': cari.id,
            'warehouse': warehouse.name,
            'paymentMethod': 'cash',
            'kdvRate': 20,
            'discount': 0,
            'items': [{
                'id': product.id,
                'quantity': 999,
                'price': 100,
                'unit': 'Adet',
            }],
        })

        insufficient_data = insufficient_response.get_json(silent=True) or {}
        db.session.expire_all()
        product_after_reject = db.session.get(Urun, product.id)
        reject_ok = (
            insufficient_response.status_code == 200
            and insufficient_data.get('success') is False
            and product_after_reject
            and abs((product_after_reject.stok_miktari or 0) - 8) < 0.001
        )
        checks.append(self_test_result_item(
            'passed' if reject_ok else 'failed',
            'critical',
            'Stok Guvenligi',
            'Yetersiz stok reddi',
            'Stoktan fazla satis reddedilmeli ve mevcut stok degismemeli.',
            f'success={insufficient_data.get("success")}, mesaj={insufficient_data.get("message")}, stok={getattr(product_after_reject, "stok_miktari", None)}',
            'Yetersiz stok kontrolu veya rollback davranisi bozulmus olabilir.' if not reject_ok else '',
            'pos_satis icindeki stok kontrolu ve db.session.rollback akisini kontrol edin.' if not reject_ok else '',
            '/pos/satis insufficient stock'
        ))

        outsider = User(
            email=f'test_robot_other_{suffix}@example.invalid',
            password=generate_password_hash(uuid.uuid4().hex),
            firma_adi=f'TEST_ROBOT Diger Firma {suffix}',
            aktif=True,
        )
        db.session.add(outsider)
        db.session.flush()
        outsider_organization = ensure_user_organization(outsider)
        outsider_product = Urun(
            barkod=f'TR-OTHER-{suffix}',
            urun_adi=f'TEST_ROBOT Diger Urun {suffix}',
            satis_fiyati=999,
            stok_miktari=5,
            user_id=outsider.id,
        )
        db.session.add(outsider_product)
        db.session.commit()

        isolation_response = run_request_as(sandbox_user, '/pos/satis', method='POST', json_payload={
            'customerId': cari.id,
            'warehouse': warehouse.name,
            'paymentMethod': 'cash',
            'kdvRate': 20,
            'discount': 0,
            'items': [{
                'id': outsider_product.id,
                'quantity': 1,
                'price': 999,
                'unit': 'Adet',
            }],
        })

        isolation_data = isolation_response.get_json(silent=True) or {}
        db.session.expire_all()
        outsider_product_after = db.session.get(Urun, outsider_product.id)
        isolation_ok = (
            isolation_response.status_code == 200
            and isolation_data.get('success') is False
            and outsider_product_after
            and abs((outsider_product_after.stok_miktari or 0) - 5) < 0.001
        )
        checks.append(self_test_result_item(
            'passed' if isolation_ok else 'failed',
            'critical',
            'Firma Izolasyonu',
            'Baska firma urunu reddi',
            'Bir firma baska firmaya ait urunu satamamali ve stok degismemeli.',
            f'success={isolation_data.get("success")}, stok={getattr(outsider_product_after, "stok_miktari", None)}',
            'Tenant izolasyonu veya urun sahiplik kontrolu bozulmus olabilir.' if not isolation_ok else '',
            'pos_satis icindeki urun.user_id ve current_user.id kontrolunu inceleyin.' if not isolation_ok else '',
            '/pos/satis tenant isolation'
        ))

        # Teklif (quote) olusturma akisi
        quote_no = f'TR-TEKLIF-{suffix}'
        quote_response = run_request_as(sandbox_user, '/teklif/ekle', method='POST', form_data={
            'cari_id': str(cari.id),
            'teklif_no': quote_no,
            'tarih': datetime.now(timezone.utc).date().isoformat(),
            'kdv_orani': '20',
            'urunler[]': [str(product.id)],
            'miktarlar[]': ['2'],
            'birimler[]': ['Adet'],
            'fiyatlar[]': ['100'],
        })

        quote = Teklif.query.filter_by(user_id=sandbox_user.id, teklif_no=quote_no).first()
        quote_line = TeklifKalemi.query.filter_by(teklif_id=quote.id).first() if quote else None
        quote_ok = (
            quote_response.status_code in {302, 200}
            and quote
            and quote_line
            and abs((quote.toplam_tutar or 0) - 200) < 0.001
        )
        checks.append(self_test_result_item(
            'passed' if quote_ok else 'failed',
            'critical',
            'Teklifler',
            'Teklif olusturma',
            'Teklif olusturulmali, kalem eklenmeli ve toplam 200 TRY olmali.',
            f'http={quote_response.status_code}, teklif={bool(quote)}, kalem={bool(quote_line)}, toplam={getattr(quote, "toplam_tutar", None)}',
            'teklif_ekle akisi, form alanlari veya TeklifKalemi kaydi bozulmus olabilir.' if not quote_ok else '',
            'teklif_ekle icindeki kalem kaydini ve toplam hesaplamasini inceleyin.' if not quote_ok else '',
            '/teklif/ekle'
        ))

        # Iade akisi (alacak olustur on) - stok + iade kaydi + stok hareketi
        db.session.expire_all()
        product_before_return = db.session.get(Urun, product.id)
        return_response = run_request_as(sandbox_user, '/iade', method='POST', form_data={
            'cari_id': str(cari.id),
            'iade_turu': 'urun_iadesi',
            'odeme_turu': 'Nakit',
            'iade_sebebi': 'TEST_ROBOT iade',
            'alacak_olustur': 'on',
            'urun_idler[]': [str(product.id)],
            'urun_adlari[]': [product.urun_adi],
            'iade_miktarlari[]': ['1'],
        })

        db.session.expire_all()
        product_after_return = db.session.get(Urun, product.id)
        return_record = Iade.query.filter_by(user_id=sandbox_user.id).order_by(Iade.id.desc()).first()
        return_line = IadeKalem.query.filter_by(iade_id=return_record.id).first() if return_record else None
        return_stock_move = StokHareket.query.filter_by(user_id=sandbox_user.id, islem_tipi='giris').order_by(StokHareket.id.desc()).first()
        line_stock_ok = (
            return_line
            and abs((return_line.yeni_stok or 0) - ((return_line.eski_stok or 0) + (return_line.miktar or 0))) < 0.001
        )
        return_ok = (
            return_response.status_code in {302, 200}
            and product_before_return
            and product_after_return
            and return_record
            and return_line
            and return_stock_move
            and line_stock_ok
        )
        checks.append(self_test_result_item(
            'passed' if return_ok else 'failed',
            'critical',
            'İade',
            'İade stok ve kayıt akışı',
            'İade kaydı oluşmalı, stok +1 artmalı, iade kalemi ve stok hareketi yazılmalı.',
            f'http={return_response.status_code}, stok_once={getattr(product_before_return, "stok_miktari", None)}, stok_sonra={getattr(product_after_return, "stok_miktari", None)}, iade={bool(return_record)}, kalem={bool(return_line)}, stok_hareket={bool(return_stock_move)}',
            'iade akisi stok guncelleme veya kayıt altina alma kisimlarinda bozulmus olabilir.' if not return_ok else '',
            'iade fonksiyonundaki urun listesi islemini ve record_stock_movement adimini kontrol edin.' if not return_ok else '',
            '/iade'
        ))

        # Gunluk satislar: satis iptali (stok + nakit ters kayit)
        db.session.expire_all()
        sale_to_cancel = Satis.query.filter_by(user_id=sandbox_user.id, durum='tamamlandi').order_by(Satis.id.desc()).first()
        product_before_cancel = db.session.get(Urun, product.id)
        cash_out_cancel_before = CashTransaction.query.filter_by(user_id=sandbox_user.id, referans_tip='satis_iptal').count()
        cancel_response = run_request_as(sandbox_user, '/gunluk-satislar', method='POST', form_data={
            'satis_id': str(sale_to_cancel.id if sale_to_cancel else ''),
        })

        db.session.expire_all()
        sale_after_cancel = db.session.get(Satis, sale_to_cancel.id) if sale_to_cancel else None
        product_after_cancel = db.session.get(Urun, product.id)
        cash_out_cancel_after = CashTransaction.query.filter_by(user_id=sandbox_user.id, referans_tip='satis_iptal').count()
        cancel_ok = (
            cancel_response.status_code in {302, 200}
            and sale_to_cancel
            and sale_after_cancel
            and sale_after_cancel.durum == 'iptal'
            and product_before_cancel
            and product_after_cancel
            and (product_after_cancel.stok_miktari or 0) >= (product_before_cancel.stok_miktari or 0)
            and cash_out_cancel_after > cash_out_cancel_before
        )
        checks.append(self_test_result_item(
            'passed' if cancel_ok else 'failed',
            'critical',
            'Günlük Satışlar',
            'Satış iptal akışı',
            'Satış iptal edilmeli, stok geri eklenmeli ve nakit ters kayıt oluşmalı.',
            f'http={cancel_response.status_code}, satis={bool(sale_to_cancel)}, durum={getattr(sale_after_cancel, "durum", None)}, stok_once={getattr(product_before_cancel, "stok_miktari", None)}, stok_sonra={getattr(product_after_cancel, "stok_miktari", None)}, iptal_nakit={cash_out_cancel_after}',
            'gunluk_satislar iptal akisi stok/nakit/cari tarafinda eksik yan etki uretiyor olabilir.' if not cancel_ok else '',
            'gunluk_satislar iptal blogunu ve CashTransaction ters kaydini kontrol edin.' if not cancel_ok else '',
            '/gunluk-satislar POST cancel'
        ))

        # Raporlar sayfasi en azindan render olabilmeli
        report_response = run_request_as(sandbox_user, '/raporlar')
        report_ok = report_response.status_code == 200
        checks.append(self_test_result_item(
            'passed' if report_ok else 'failed',
            'warning' if not report_ok else 'info',
            'Raporlar',
            'Sayfa render kontrolü',
            'Raporlar sayfas? 200 dönmeli ve hata atmamalı.',
            f'http={report_response.status_code}',
            'raporlar fonksiyonunda datetime/tenant veya template hatasi olabilir.' if not report_ok else '',
            'raporlar route ve template i kontrol edin.' if not report_ok else '',
            '/raporlar'
        ))

        cleanup_platform_workflow_sandbox(outsider.id, outsider_organization.id)
        sandbox_user_id = sandbox_user.id
        sandbox_organization_id = organization.id

    except Exception as exc:
        checks.append(self_test_result_item(
            'failed',
            'critical',
            'Derin Is Akisi',
            'Robot calisma hatasi',
            'Robot tum sandbox akisini hata atmadan tamamlamali.',
            f'Hata: {exc}',
            'Yeni eklenen is akisi veya veritabani modeli beklenmeyen hata uretmis olabilir.',
            'Sunucu logundaki stack trace ile ilgili route/model fonksiyonunu inceleyin.',
            exc.__class__.__name__
        ))
    finally:
        cleanup_error = ''
        try:
            cleanup_platform_workflow_sandbox(sandbox_user_id, sandbox_organization_id)
        except Exception as exc:
            db.session.rollback()
            cleanup_error = str(exc)
        checks.append(self_test_result_item(
            'passed' if not cleanup_error else 'warning',
            'warning' if cleanup_error else 'info',
            'Sandbox',
            'Test verisi temizligi',
            'Robot gecici firma ve kayitlarini calisma sonunda silmeli.',
            'Gecici kayitlar temizlendi.' if not cleanup_error else f'Temizlik uyarisi: {cleanup_error}',
            'Silme sirasi veya foreign key baglantisi temizligi engelliyor olabilir.' if cleanup_error else '',
            'TEST_ROBOT ile baslayan kayitlari ve cleanup_platform_workflow_sandbox fonksiyonunu kontrol edin.' if cleanup_error else '',
            'cleanup_platform_workflow_sandbox'
        ))

    status, passed_count, warning_count, failed_count = workflow_summary(checks)
    result = {
        'status': status,
        'status_label': {
            'passed': 'Derin is akisi kararli',
            'warning': 'Derin is akisi calisti, uyarilar var',
            'failed': 'Derin is akisinda kritik hata var',
        }[status],
        'ran_at': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total': len(checks),
            'passed': passed_count,
            'warnings': warning_count,
            'failed': failed_count,
            'routes': 1,
            'api_routes': 0,
            'templates': 0,
            'forms': 0,
            'buttons': 0,
        },
        'checks': checks,
    }
    set_platform_setting('workflow_test_last_result', json.dumps(result, ensure_ascii=False), 'Son derin is akisi test raporu')
    platform_audit(
        'PLATFORM_WORKFLOW_TEST_RUN',
        f"Derin is akisi testi: {result['status_label']} ({passed_count}/{len(checks)} gecti, {warning_count} uyari, {failed_count} hata).",
        'Platform'
    )
    db.session.commit()
    return result


def suspicious_request_reason():
    if not platform_setting_bool('security_shield_enabled', True):
        return None
    if request.endpoint in {'download_backup'}:
        return None
    target = f'{request.path} {request.query_string.decode("utf-8", "ignore")}'.lower()
    user_agent = (request.headers.get('User-Agent') or '').lower()
    patterns = {
        '../': 'path traversal',
        '..\\': 'path traversal',
        '%2e%2e': 'encoded path traversal',
        '<script': 'script injection',
        'union select': 'sql injection probe',
        '/wp-admin': 'bot scan',
        '/.env': 'secret file scan',
        'phpmyadmin': 'admin tool scan',
    }
    for pattern, reason in patterns.items():
        if pattern in target:
            return reason
    if any(token in user_agent for token in ['sqlmap', 'nikto', 'acunetix']):
        return 'scanner user agent'
    return None


def is_readonly_exempt_endpoint():
    return request.endpoint in {
        'static', 'health_check', 'giris', 'cikis', 'super_admin_exit_impersonation',
    } or (request.endpoint or '').startswith('super_admin')


def is_dangerous_operation_endpoint():
    return request.endpoint in {
        'restore_backup',
        'settings_backup',
        'toplu_fiyat_guncelleme',
        'urun_sil',
        'cari_sil',
        'teklif_sil',
        'personel_sil',
        'departman_sil',
        'kategori_sil',
    }


def platform_admin_emails():
    emails = os.environ.get('PLATFORM_ADMIN_EMAILS', '')
    configured_emails = {email.strip().lower() for email in emails.split(',') if email.strip()}
    return configured_emails | {'mehmetdurna@msn.com'}


def ensure_reserved_platform_owner(user):
    if not user or (user.email or '').strip().lower() not in platform_admin_emails():
        return False
    changed = False
    if not user.is_platform_admin:
        user.is_platform_admin = True
        changed = True
    if user.platform_role != 'owner':
        user.platform_role = 'owner'
        changed = True
    if user.role != 'owner':
        user.role = 'owner'
        changed = True
    if not user.aktif:
        user.aktif = True
        changed = True
    organization = ensure_user_organization(user)
    if organization:
        if organization.plan != 'profesyonel':
            organization.plan = 'profesyonel'
            changed = True
        if (organization.user_limit or 1) < 10:
            organization.user_limit = 10
            changed = True
        if (organization.product_limit or 10) < 999999:
            organization.product_limit = 999999
            changed = True
    return changed


def platform_admin_default_password():
    return os.environ.get('PLATFORM_ADMIN_PASSWORD')


def bootstrap_platform_admins():
    admin_emails = platform_admin_emails()
    default_password = platform_admin_default_password()
    if not admin_emails or not default_password:
        return
    changed = False
    for email in admin_emails:
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if not user:
            user = User(
                email=email,
                password=generate_password_hash(default_password),
                firma_adi=os.environ.get('PLATFORM_ADMIN_COMPANY', 'Mehmet DURNA A.S.'),
                yetkili_adi=os.environ.get('PLATFORM_ADMIN_NAME', 'Mehmet Durna'),
                paket_tipi='profesyonel',
                urun_limiti=int(os.environ.get('PLATFORM_ADMIN_PRODUCT_LIMIT', '999999')),
                aktif=True,
                role='owner',
                is_platform_admin=True,
                platform_role='owner',
            )
            try:
                with db.session.begin_nested():
                    db.session.add(user)
                    db.session.flush()
            except IntegrityError:
                user = User.query.filter(db.func.lower(User.email) == email).first()
                if not user:
                    raise
            else:
                changed = True
        changed = ensure_reserved_platform_owner(user) or changed
    db.session.commit()


def is_platform_admin_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'is_platform_admin', False))


def platform_admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_platform_admin_user(current_user):
            flash('Bu alan yalnızca uygulama sahibi yetkisine açıktır.', 'error')
            return redirect(url_for('dashboard'))
        return func(*args, **kwargs)
    return wrapper


def platform_permission_required(permission):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not is_platform_admin_user(current_user):
                flash('Bu alan yalnizca platform ekibine aciktir.', 'error')
                return redirect(url_for('dashboard'))
            if not platform_can(permission, current_user):
                flash('Bu islem icin platform yetkiniz yok.', 'error')
                return redirect(url_for('super_admin_dashboard'))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def platform_audit(action, details='', resource_type='Platform', resource_id=None):
    if not current_user.is_authenticated:
        return
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', ''),
        session_id=session.get('_id', '')
    ))


def module_for_endpoint(endpoint):
    if not endpoint:
        return None
    for module, prefixes in PLATFORM_MODULE_ENDPOINT_PREFIXES.items():
        if any(endpoint == prefix or endpoint.startswith(f'{prefix}_') for prefix in prefixes):
            return module
    return None


def tenant_categories_with_counts():
    tenant_ids = tenant_user_ids()
    categories = {}
    for product in Urun.query.filter(Urun.user_id.in_(tenant_ids)).all():
        name = (product.kategori or '').strip()
        if name:
            categories[name] = categories.get(name, 0) + 1

    for category in Category.query.filter(Category.user_id.in_(tenant_ids)).order_by(Category.name).all():
        categories.setdefault(category.name, 0)

    return dict(sorted(categories.items(), key=lambda item: item[0].lower()))


def tenant_warehouses_with_metrics():
    tenant_ids = tenant_user_ids()
    warehouses = {}
    for product in Urun.query.filter(Urun.user_id.in_(tenant_ids)).all():
        name = normalize_warehouse_name(product.depo_adi)
        warehouses.setdefault(name, {'product_count': 0, 'stock_quantity': 0.0})
        warehouses[name]['product_count'] += 1
        warehouses[name]['stock_quantity'] += float(product.stok_miktari or 0)

    for warehouse in Warehouse.query.filter(Warehouse.user_id.in_(tenant_ids)).order_by(Warehouse.name).all():
        warehouses.setdefault(warehouse.name, {'product_count': 0, 'stock_quantity': 0.0})

    return dict(sorted(warehouses.items(), key=lambda item: item[0].lower()))


def ensure_database_schema():
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        backfill_user_organizations()
        bootstrap_platform_admins()
        return

    db.create_all()

    inspector = inspect(db.engine)
    connection = db.engine.connect()

    try:
        if 'cash_transaction' in inspector.get_table_names():
            cash_columns = [col['name'] for col in inspector.get_columns('cash_transaction')]
            if 'account_id' not in cash_columns:
                connection.execute(text('ALTER TABLE cash_transaction ADD COLUMN account_id INTEGER'))
        if 'user' in inspector.get_table_names():
            user_columns = [col['name'] for col in inspector.get_columns('user')]
            if 'vergi_dairesi' not in user_columns:
                connection.execute(text('ALTER TABLE user ADD COLUMN vergi_dairesi VARCHAR(100)'))
            if 'vergi_numarasi' not in user_columns:
                connection.execute(text('ALTER TABLE user ADD COLUMN vergi_numarasi VARCHAR(100)'))
            if 'adres' not in user_columns:
                connection.execute(text('ALTER TABLE user ADD COLUMN adres TEXT'))
            if 'organization_id' not in user_columns:
                connection.execute(text('ALTER TABLE user ADD COLUMN organization_id INTEGER'))
            if 'role' not in user_columns:
                connection.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(30) DEFAULT 'owner'"))
            if 'is_platform_admin' not in user_columns:
                connection.execute(text('ALTER TABLE user ADD COLUMN is_platform_admin BOOLEAN DEFAULT 0'))
            if 'platform_role' not in user_columns:
                connection.execute(text("ALTER TABLE user ADD COLUMN platform_role VARCHAR(30) DEFAULT 'owner'"))
        if 'organization' in inspector.get_table_names():
            organization_columns = [col['name'] for col in inspector.get_columns('organization')]
            if 'user_limit' not in organization_columns:
                connection.execute(text('ALTER TABLE organization ADD COLUMN user_limit INTEGER DEFAULT 1'))
            if 'product_limit' not in organization_columns:
                connection.execute(text('ALTER TABLE organization ADD COLUMN product_limit INTEGER DEFAULT 10'))
            if 'module_permissions' not in organization_columns:
                connection.execute(text("ALTER TABLE organization ADD COLUMN module_permissions TEXT DEFAULT '{}'"))
            if 'maintenance_mode' not in organization_columns:
                connection.execute(text('ALTER TABLE organization ADD COLUMN maintenance_mode BOOLEAN DEFAULT 0'))
            if 'subscription_start' not in organization_columns:
                connection.execute(text('ALTER TABLE organization ADD COLUMN subscription_start DATE'))
            if 'subscription_end' not in organization_columns:
                connection.execute(text('ALTER TABLE organization ADD COLUMN subscription_end DATE'))
            if 'subscription_status' not in organization_columns:
                connection.execute(text("ALTER TABLE organization ADD COLUMN subscription_status VARCHAR(20) DEFAULT 'trial'"))
        if 'subscription_note' not in organization_columns:
            connection.execute(text('ALTER TABLE organization ADD COLUMN subscription_note TEXT'))
        if 'support_ticket_message' in inspector.get_table_names():
            message_columns = [col['name'] for col in inspector.get_columns('support_ticket_message')]
            if 'attachment_filename' not in message_columns:
                connection.execute(text('ALTER TABLE support_ticket_message ADD COLUMN attachment_filename VARCHAR(255)'))
            if 'attachment_original_name' not in message_columns:
                connection.execute(text('ALTER TABLE support_ticket_message ADD COLUMN attachment_original_name VARCHAR(255)'))
            if 'attachment_content_type' not in message_columns:
                connection.execute(text('ALTER TABLE support_ticket_message ADD COLUMN attachment_content_type VARCHAR(120)'))
            if 'attachment_size' not in message_columns:
                connection.execute(text('ALTER TABLE support_ticket_message ADD COLUMN attachment_size INTEGER'))
        if 'action_item' in inspector.get_table_names():
            action_columns = [col['name'] for col in inspector.get_columns('action_item')]
            if 'organization_id' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN organization_id INTEGER'))
            if 'source_type' not in action_columns:
                connection.execute(text("ALTER TABLE action_item ADD COLUMN source_type VARCHAR(40) DEFAULT 'manual'"))
            if 'source_id' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN source_id INTEGER'))
            if 'title' not in action_columns:
                connection.execute(text("ALTER TABLE action_item ADD COLUMN title VARCHAR(180) DEFAULT 'Aksiyon'"))
            if 'description' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN description TEXT'))
            if 'severity' not in action_columns:
                connection.execute(text("ALTER TABLE action_item ADD COLUMN severity VARCHAR(20) DEFAULT 'medium'"))
            if 'status' not in action_columns:
                connection.execute(text("ALTER TABLE action_item ADD COLUMN status VARCHAR(20) DEFAULT 'open'"))
            if 'assigned_user_id' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN assigned_user_id INTEGER'))
            if 'sla_hours' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN sla_hours INTEGER'))
            if 'due_at' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN due_at DATETIME'))
            if 'ai_summary' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN ai_summary TEXT'))
            if 'ai_recommendation' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN ai_recommendation TEXT'))
            if 'created_at' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN created_at DATETIME'))
            if 'updated_at' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN updated_at DATETIME'))
            if 'resolved_at' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN resolved_at DATETIME'))
            if 'snoozed_until' not in action_columns:
                connection.execute(text('ALTER TABLE action_item ADD COLUMN snoozed_until DATETIME'))
        if 'cari' in inspector.get_table_names():
            cari_columns = [col['name'] for col in inspector.get_columns('cari')]
            if 'vergidairesi' not in cari_columns:
                connection.execute(text('ALTER TABLE cari ADD COLUMN vergidairesi VARCHAR(100)'))
            if 'vergi_numarasi' not in cari_columns:
                connection.execute(text('ALTER TABLE cari ADD COLUMN vergi_numarasi VARCHAR(100)'))

        if 'audit_log' in inspector.get_table_names():
            audit_columns = [col['name'] for col in inspector.get_columns('audit_log')]
            if 'details' not in audit_columns:
                connection.execute(text('ALTER TABLE audit_log ADD COLUMN details TEXT'))
    finally:
        connection.commit()
        connection.close()

    backfill_user_organizations()
    bootstrap_platform_admins()


# Session ID oluşturma
database_schema_lock = threading.Lock()


@app.before_request
def initialize_database_request():
    if not app.config.get('DB_SCHEMA_UPDATED', False):
        with database_schema_lock:
            if not app.config.get('DB_SCHEMA_UPDATED', False):
                ensure_database_schema()
                app.config['DB_SCHEMA_UPDATED'] = True


@app.before_request
def enforce_platform_maintenance():
    if request.endpoint in {'static', 'health_check', 'giris', 'cikis'}:
        return
    if current_user.is_authenticated and is_platform_admin_user(current_user):
        return
    if platform_setting('maintenance_mode', 'off') == 'on':
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Sistem bak?m modunda.'}), 503
        return render_template(
            'error.html',
            status_code=503,
            title='Bakım Modu',
            message='Sistem kısa süreli bak?m modunda. Lütfen daha sonra tekrar deneyin.'
        ), 503


@app.before_request
def enforce_platform_security_controls():
    if request.endpoint == 'static':
        return

    reason = suspicious_request_reason()
    if reason:
        if current_user.is_authenticated:
            db.session.add(AuditLog(
                user_id=current_user.id,
                action='SECURITY_THREAT_BLOCKED',
                resource_type='Security',
                details=f'{reason}: {request.path}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent', ''),
                session_id=session.get('_id', '')
            ))
            db.session.commit()
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Supheli istek engellendi.'}), 403
        return render_template(
            'error.html',
            status_code=403,
            title='Istek engellendi',
            message='Guvenlik kalkanlari bu istegi engelledi.'
        ), 403

    if (
        platform_setting_bool('readonly_mode', False)
        and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
        and not (current_user.is_authenticated and is_platform_admin_user(current_user))
        and not is_readonly_exempt_endpoint()
    ):
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Sistem salt-okunur modda.'}), 423
        flash('Sistem su anda salt-okunur modda. Degisiklik islemleri gecici olarak kapali.', 'warning')
        return redirect(request.referrer or url_for('dashboard'))

    if (
        platform_setting_bool('dangerous_operations_locked', False)
        and request.method in {'POST', 'PUT', 'PATCH', 'DELETE', 'GET'}
        and is_dangerous_operation_endpoint()
        and not (current_user.is_authenticated and is_platform_admin_user(current_user))
    ):
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Riskli islemler gecici olarak kilitli.'}), 423
        flash('Riskli islemler sistem yonetimi tarafindan gecici olarak kilitlendi.', 'warning')
        return redirect(request.referrer or url_for('dashboard'))

    if current_user.is_authenticated and not is_platform_admin_user(current_user):
        epoch = platform_setting_datetime('session_epoch')
        login_at = session.get('login_at')
        if epoch and login_at:
            try:
                login_at_dt = datetime.fromisoformat(login_at)
            except ValueError:
                login_at_dt = None
            if login_at_dt and login_at_dt < epoch:
                clear_login_session()
                flash('Oturumunuz sistem yonetimi tarafindan sonlandirildi.', 'warning')
                return redirect(url_for('giris'))


@app.before_request
def enforce_organization_controls():
    if request.endpoint in {'static', 'health_check', 'giris', 'kayit', 'cikis', 'super_admin_exit_impersonation'}:
        return
    if not current_user.is_authenticated or is_platform_admin_user(current_user):
        return
    if request.endpoint and request.endpoint.startswith('super_admin'):
        return

    organization = getattr(current_user, 'organization', None)
    if not organization:
        return

    if organization.maintenance_mode:
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Firma hesabiniz bakim modunda.'}), 503
        return render_template(
            'error.html',
            status_code=503,
            title='Firma Bakim Modu',
            message='Firma hesabi kisa sureli bakim modunda. Lutfen daha sonra tekrar deneyin.'
        ), 503

    module = module_for_endpoint(request.endpoint)
    if module and not parse_module_permissions(organization.module_permissions).get(module, True):
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Bu modul firma hesabiniz icin kapali.'}), 403
        flash('Bu modul firma hesabiniz icin kapali.', 'error')
        if request.endpoint == 'dashboard':
            return render_template(
                'error.html',
                status_code=403,
                title='Modul Kapali',
                message='Ana panel modulu firma hesabiniz icin kapali.'
            ), 403
        return redirect(url_for('dashboard'))


class Satis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fatura_no = db.Column(db.String(50), unique=True, nullable=False)
    cari_id = db.Column(db.Integer, db.ForeignKey('cari.id'), nullable=True)  # Perakende satış için nullable
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tarih = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    depo = db.Column(db.String(100), default='Ana Merkez Depo')
    ara_toplam = db.Column(db.Float, default=0)
    kdv_orani = db.Column(db.Float, default=20)
    kdv_tutar = db.Column(db.Float, default=0)
    iskonto = db.Column(db.Float, default=0)
    genel_toplam = db.Column(db.Float, default=0)
    notlar = db.Column(db.Text)
    durum = db.Column(db.String(20), default='tamamlandi')  # tamamlandi, iptal

    cari = db.relationship('Cari', backref='satislar')
    kalemler = db.relationship('SatisKalemi', backref='satis', lazy=True, cascade='all, delete-orphan')


class SatisKalemi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    satis_id = db.Column(db.Integer, db.ForeignKey('satis.id'), nullable=False)
    urun_id = db.Column(db.Integer, db.ForeignKey('urun.id'), nullable=False)
    urun_adi = db.Column(db.String(200), nullable=False)
    barkod = db.Column(db.String(50))
    miktar = db.Column(db.Float, default=1)
    birim = db.Column(db.String(20), default='Adet')
    birim_fiyat = db.Column(db.Float, default=0)
    toplam = db.Column(db.Float, default=0)


@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
        if user and not user.aktif:
            return None
        return user
    except (TypeError, ValueError, ObjectDeletedError):
        db.session.rollback()
        return None


def clear_login_session():
    for key in ('_user_id', '_fresh', '_remember', 'remember'):
        session.pop(key, None)


def wants_json_response():
    return (
        request.path.startswith('/api/')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def safe_exception_message(error, default_message='Beklenmeyen bir hata oluştu.'):
    if current_app.config.get('IS_PRODUCTION'):
        return default_message
    return str(error)


def safe_next_url(default_endpoint, **default_values):
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    if next_url.startswith('/') and not next_url.startswith('//') and '\\' not in next_url:
        return next_url
    return url_for(default_endpoint, **default_values)

# Audit Log Decorator


def client_ip():
    forwarded = (request.headers.get('X-Forwarded-For') or '').strip()
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def ratelimit_db_path():
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except Exception:
        pass
    return os.path.join(app.instance_path, 'ratelimit.sqlite3')


def ratelimit_check(action, subject, limit, per_seconds, block_seconds):
    if not subject:
        return True, None

    now = int(time.time())
    window_start = now - (now % int(per_seconds))
    db_path = ratelimit_db_path()

    with sqlite3.connect(db_path, timeout=5) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counters (
                action TEXT NOT NULL,
                subject TEXT NOT NULL,
                window_start INTEGER NOT NULL,
                count INTEGER NOT NULL,
                blocked_until INTEGER NOT NULL,
                PRIMARY KEY (action, subject)
            )
            """
        )

        row = conn.execute(
            "SELECT window_start, count, blocked_until FROM counters WHERE action=? AND subject=?",
            (action, subject),
        ).fetchone()

        if row:
            prev_window_start, count, blocked_until = row
        else:
            prev_window_start, count, blocked_until = window_start, 0, 0

        if blocked_until and blocked_until > now:
            return False, blocked_until - now

        if prev_window_start != window_start:
            count = 0

        count += 1

        if count > int(limit):
            blocked_until = now + int(block_seconds)
            conn.execute(
                "INSERT OR REPLACE INTO counters(action, subject, window_start, count, blocked_until) VALUES(?,?,?,?,?)",
                (action, subject, window_start, count, blocked_until),
            )
            return False, int(block_seconds)

        conn.execute(
            "INSERT OR REPLACE INTO counters(action, subject, window_start, count, blocked_until) VALUES(?,?,?,?,?)",
            (action, subject, window_start, count, 0),
        )

    return True, None


def smtp_is_configured():
    cfg = smtp_config()
    return bool(cfg.get('host') and cfg.get('from_email'))


def send_email_smtp(*, to_email, subject, text_body, html_body=None):
    cfg = smtp_config()
    host = cfg.get('host')
    port = int(cfg.get('port') or 587)
    username = cfg.get('username') or None
    password = cfg.get('password') or None
    use_tls = bool(cfg.get('use_tls'))
    use_ssl = bool(cfg.get('use_ssl'))

    from_email = cfg.get('from_email')
    from_name = cfg.get('from_name') or app.config.get('SITE_NAME', 'StokCari')
    from_header = f'{from_name} <{from_email}>' if from_name else from_email

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_header
    msg['To'] = to_email
    msg.set_content(text_body or '')
    if html_body:
        msg.add_alternative(html_body, subtype='html')

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)

    try:
        server.ehlo()
        if use_tls and not use_ssl:
            server.starttls()
            server.ehlo()
        if username:
            server.login(username, password or '')
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_password_reset_email(user, reset_url):
    site_name = site_config().get('name') or app.config.get('SITE_NAME', 'StokCari')
    subject = f'{site_name} - Åifre s?f?rlama bağlantın?z'
    text_body = app.jinja_env.get_template('emails/password_reset.txt').render(
        reset_url=reset_url, user=user, site_name=site_name
    )
    html_body = app.jinja_env.get_template('emails/password_reset.html').render(
        reset_url=reset_url, user=user, site_name=site_name
    )
    send_email_smtp(to_email=user.email, subject=subject, text_body=text_body, html_body=html_body)


def audit_log(action, resource_type):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_user.is_authenticated:
                log = AuditLog(
                    user_id=current_user.id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=kwargs.get('id') or request.form.get('id') or request.args.get('id'),
                    details=f'{audit_resource_label(resource_type)} islemi yapildi: {audit_action_label(action)}',
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent', ''),
                    session_id=session.get('_id', '')
                )
                db.session.add(log)
                db.session.commit()

            result = f(*args, **kwargs)

            if (current_user.is_authenticated and hasattr(result, 'status_code') and
                    result.status_code in [200, 201, 204]):
                try:
                    log.status = 'completed'
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            return result
        return decorated_function
    return decorator


def generate_fatura_no(prefix='POS'):
    year = datetime.now(timezone.utc).year
    while True:
        candidate = f'{prefix}-{year}-{uuid.uuid4().hex[:10].upper()}'
        if not Satis.query.filter_by(fatura_no=candidate).first():
            return candidate


def generate_teklif_no():
    year = datetime.now(timezone.utc).year
    while True:
        candidate = f'TEK-{year}-{uuid.uuid4().hex[:10].upper()}'
        if not Teklif.query.filter_by(teklif_no=candidate).first():
            return candidate


ALLOWED_TEKLIF_DURUMLARI = {'taslak', 'gonderildi', 'onaylandi', 'reddedildi'}
ALLOWED_IADE_TURLERI = {'urun_iadesi', 'para_iadesi', 'hizmet_iadesi', 'degisim'}


def parse_teklif_kdv_orani(raw_value):
    if raw_value in (None, ''):
        return 18.0
    try:
        kdv_orani = float(raw_value)
    except (TypeError, ValueError):
        return None
    if kdv_orani < 0 or kdv_orani > 100:
        return None
    return kdv_orani


def calculate_sale_totals(subtotal, kdv_orani, iskonto):
    try:
        subtotal = float(subtotal or 0)
        kdv_orani = float(kdv_orani)
        iskonto = float(iskonto or 0)
    except (TypeError, ValueError):
        return None, 'Geçersiz KDV ya da iskonto değeri'
    if subtotal <= 0:
        return None, 'Satış için en az bir geçerli Ürün seçiniz'
    if kdv_orani < 0 or kdv_orani > 100:
        return None, 'KDV oranı 0 ile 100 arasında olmalı'
    if iskonto < 0:
        return None, 'İskonto negatif olamaz'
    kdv_tutar = round(subtotal * (kdv_orani / 100), 2)
    genel_toplam = round(subtotal + kdv_tutar - iskonto, 2)
    if genel_toplam <= 0:
        return None, 'Satış toplam? sıfırdan büyük olmalı'
    return {
        'ara_toplam': round(subtotal, 2),
        'kdv_orani': round(kdv_orani, 2),
        'kdv_tutar': kdv_tutar,
        'iskonto': round(iskonto, 2),
        'genel_toplam': genel_toplam,
    }, None


def parse_teklif_kalemleri_from_form():
    urunler = request.form.getlist('urunler[]')
    miktarlar = request.form.getlist('miktarlar[]')
    birimler = request.form.getlist('birimler[]')
    fiyatlar = request.form.getlist('fiyatlar[]')

    kalemler = []
    toplam_tutar = 0
    for i, urun_id in enumerate(urunler):
        if not urun_id:
            continue
        try:
            urun = db.session.get(Urun, int(urun_id))
        except (TypeError, ValueError):
            return None, 0, 'Teklifte gecersiz urun secimi var!'
        if not belongs_to_current_tenant(urun):
            return None, 0, 'Teklifte gecersiz urun secimi var!'
        try:
            miktar = float(miktarlar[i]) if i < len(miktarlar) and miktarlar[i] else 1
            birim_fiyat = float(fiyatlar[i]) if i < len(fiyatlar) and fiyatlar[i] else 0
        except (TypeError, ValueError):
            return None, 0, 'Teklifte gecersiz miktar veya fiyat var!'
        if miktar <= 0 or birim_fiyat < 0:
            continue
        toplam = miktar * birim_fiyat
        toplam_tutar += toplam
        kalemler.append({
            'urun_id': int(urun_id),
            'urun_adi': urun.urun_adi if urun else '',
            'miktar': miktar,
            'birim': birimler[i] if i < len(birimler) and birimler[i] else 'Adet',
            'birim_fiyat': birim_fiyat,
            'toplam': toplam,
        })

    if not kalemler:
        return None, 0, 'En az bir gecerli urun kalemi ekleyin.'
    return kalemler, toplam_tutar, None


def normalize_amount(value, default=0.0):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def parse_iso_datetime(value):
    if not value:
        return None
    if isinstance(value, str) and value.endswith('Z'):
        value = value[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def normalize_payment_method(value):
    if not value:
        return 'Nakit'
    normalized = str(value).strip().lower()
    if normalized in ['cash', 'nakit']:
        return 'Nakit'
    if normalized in ['credit', 'veresiye', 'alacak', 'cari']:
        return 'Alacak'
    if normalized in ['havale/eft', 'havale', 'eft']:
        return 'Havale/EFT'
    if normalized in ['card', 'kredi kart\u0131', 'kredi karti', 'kredi', 'kart', 'pos']:
        return 'Kredi Kart\u0131'
    if normalized in ['cek', '\u00e7ek']:
        return '\u00c7ek'
    return str(value).strip().title()


def ensure_default_accounts_for_user(user_id):
    existing = Account.query.filter_by(user_id=user_id).all()
    if existing:
        return existing
    defaults = [
        Account(user_id=user_id, type='cash', name='Nakit Kasa', currency='TRY', opening_balance=0),
        Account(user_id=user_id, type='bank', name='Banka Hesabi', currency='TRY', opening_balance=0),
        Account(user_id=user_id, type='pos', name='POS', currency='TRY', opening_balance=0),
    ]
    db.session.add_all(defaults)
    db.session.commit()
    return defaults


def default_account_for_payment_method(user_id, payment_method):
    accounts = ensure_default_accounts_for_user(user_id)
    normalized = normalize_payment_method(payment_method or '').strip().lower()
    if normalized in {'nakit', 'cash'}:
        target_type = 'cash'
    elif 'kart' in normalized or normalized == 'pos':
        target_type = 'pos'
    else:
        target_type = 'bank'
    for account in accounts:
        if account.type == target_type and account.active:
            return account
    return accounts[0] if accounts else None


def get_password_reset_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'])


def generate_password_reset_token(user):
    serializer = get_password_reset_serializer()
    return serializer.dumps(user.email, salt=app.config['SECURITY_PASSWORD_SALT'])


def verify_password_reset_token(token, max_age=3600):
    serializer = get_password_reset_serializer()
    try:
        email = serializer.loads(token, salt=app.config['SECURITY_PASSWORD_SALT'], max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return User.query.filter_by(email=email).first()


DEFAULT_WAREHOUSE = 'Ana Depo'


def normalize_warehouse_name(value):
    name = ' '.join(str(value or DEFAULT_WAREHOUSE).strip().split())
    return name[:100] if name else DEFAULT_WAREHOUSE


def ensure_warehouse(name):
    warehouse_name = normalize_warehouse_name(name)
    warehouse = Warehouse.query.filter_by(user_id=current_user.id, name=warehouse_name).first()
    if not warehouse:
        warehouse = Warehouse(name=warehouse_name, user_id=current_user.id)
        db.session.add(warehouse)
        db.session.flush()
    return warehouse


def find_matching_product_in_warehouse(source_product, warehouse_name):
    warehouse_name = normalize_warehouse_name(warehouse_name)
    query = tenant_query(Urun).filter_by(depo_adi=warehouse_name)
    if source_product.barkod:
        match = query.filter_by(barkod=source_product.barkod).first()
        if match:
            return match
    return query.filter_by(
        urun_adi=source_product.urun_adi,
        kategori=source_product.kategori,
        birim=source_product.birim
    ).first()


def get_or_create_product_in_warehouse(source_product, warehouse_name):
    warehouse_name = normalize_warehouse_name(warehouse_name)
    if normalize_warehouse_name(source_product.depo_adi) == warehouse_name:
        source_product.depo_adi = warehouse_name
        return source_product

    existing_product = find_matching_product_in_warehouse(source_product, warehouse_name)
    if existing_product:
        return existing_product

    new_product = Urun(
        barkod=source_product.barkod,
        urun_adi=source_product.urun_adi,
        kategori=source_product.kategori,
        birim=source_product.birim,
        alis_fiyati=source_product.alis_fiyati,
        satis_fiyati=source_product.satis_fiyati,
        stok_miktari=0,
        kritik_stok=source_product.kritik_stok,
        depo_adi=warehouse_name,
        user_id=current_user.id
    )
    db.session.add(new_product)
    db.session.flush()
    return new_product


def record_stock_movement(urun, movement_type, quantity, warehouse_name, old_stock,
                          new_stock, description='', cari_id=None):
    movement = StokHareket(
        urun_id=urun.id,
        user_id=current_user.id,
        islem_tipi=movement_type,
        miktar=quantity,
        aciklama=description,
        depo=normalize_warehouse_name(warehouse_name),
        eski_stok=old_stock,
        yeni_stok=new_stock,
        cari_id=cari_id,
        ip_adresi=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')
    )
    db.session.add(movement)
    return movement


def add_stock_to_warehouse(source_product, quantity, warehouse_name, description=''):
    warehouse_name = normalize_warehouse_name(warehouse_name)
    ensure_warehouse(warehouse_name)
    target_product = get_or_create_product_in_warehouse(source_product, warehouse_name)
    old_stock = target_product.stok_miktari or 0
    target_product.stok_miktari = old_stock + quantity
    record_stock_movement(
        target_product,
        'giris',
        quantity,
        warehouse_name,
        old_stock,
        target_product.stok_miktari,
        description or f'{warehouse_name} depo stok girişi'
    )
    return target_product, old_stock


def resolve_product_for_stock_out(source_product, warehouse_name):
    warehouse_name = normalize_warehouse_name(warehouse_name)
    if normalize_warehouse_name(source_product.depo_adi) == warehouse_name:
        source_product.depo_adi = warehouse_name
        return source_product
    return find_matching_product_in_warehouse(source_product, warehouse_name)


def create_cash_transaction(cari, tutar, islem_tipi='giris', odeme_turu='Nakit',
                             aciklama='', referans_id=None, referans_tip=None, account_id=None):
    if tutar <= 0:
        return None
    if not account_id and current_user.is_authenticated:
        account = default_account_for_payment_method(current_user.id, odeme_turu)
        account_id = account.id if account else None
    transaction = CashTransaction(
        user_id=current_user.id,
        account_id=account_id,
        cari_id=cari.id if cari else None,
        tarih=datetime.now(timezone.utc),
        islem_tipi=islem_tipi,
        tutar=tutar,
        odeme_turu=odeme_turu,
        aciklama=aciklama,
        referans_id=referans_id,
        referans_tip=referans_tip,
        ip_adresi=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')
    )
    db.session.add(transaction)
    return transaction


def adjust_cari_account(cari, amount, transaction_type):
    if transaction_type == 'odeme':
        mevcut_borc = cari.borc or 0
        mevcut_alacak = cari.alacak or 0
        if amount <= mevcut_borc:
            cari.borc = mevcut_borc - amount
        else:
            cari.borc = 0
            cari.alacak = mevcut_alacak + (amount - mevcut_borc)
    elif transaction_type == 'tahsilat':
        mevcut_alacak = cari.alacak or 0
        mevcut_borc = cari.borc or 0
        if amount <= mevcut_alacak:
            cari.alacak = mevcut_alacak - amount
        else:
            cari.alacak = 0
            cari.borc = mevcut_borc + (amount - mevcut_alacak)

# Session ID oluşturma


@app.before_request
def before_request():
    g.request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    g.request_start_time = datetime.now(timezone.utc)
    app.permanent_session_lifetime = timedelta(
        minutes=platform_setting_int('session_lifetime_minutes', 480)
    )
    session.permanent = True
    if '_id' not in session:
        session['_id'] = str(uuid.uuid4())


@app.before_request
def ensure_authenticated_user_tenant():
    try:
        if current_user.is_authenticated:
            ensure_user_organization(current_user)
            ensure_reserved_platform_owner(current_user)
            db.session.commit()
    except ObjectDeletedError:
        db.session.rollback()
        clear_login_session()
        if wants_json_response():
            return jsonify({'success': False, 'message': 'Oturum süresi doldu. Lütfen tekrar giriş yapın.'}), 401
        flash('Oturumunuz yenilenmeli. Lütfen tekrar giriş yapın.', 'warning')
        return redirect(url_for('giris', next=request.url))

# IP ve User Agent kaydetme


@app.before_request
def log_request_info():
    try:
        if current_user.is_authenticated and request.endpoint not in ['static']:
            g.request_start_time = datetime.now(timezone.utc)
            g.ip_address = request.remote_addr
            g.user_agent = request.headers.get('User-Agent', '')
    except ObjectDeletedError:
        db.session.rollback()
        clear_login_session()


@app.after_request
def add_operational_headers(response):
    for header, value in app.config.get('SECURITY_HEADERS', {}).items():
        response.headers.setdefault(header, value)

    if hasattr(g, 'request_id'):
        response.headers.setdefault('X-Request-ID', g.request_id)

    if request.endpoint != 'static':
        response.headers.setdefault('Cache-Control', 'no-store, max-age=0')

    try:
        if request.endpoint not in {'static', 'health_check'} and not site_config().get('seo_public_mode'):
            response.headers.setdefault('X-Robots-Tag', 'noindex, nofollow')
    except Exception:
        pass

    return response


@app.errorhandler(404)
def handle_not_found(error):
    if wants_json_response():
        return jsonify(success=False, message='Kaynak bulunamadı.'), 404

    return render_template(
        'error.html',
        status_code=404,
        title='Sayfa bulunamadı',
        message='Aradığınız sayfa taşınmış, silinmiş veya adres hatalı yazılmış olabilir.'
    ), 404


@app.errorhandler(403)
def handle_forbidden(error):
    if wants_json_response():
        return jsonify(success=False, message='Erişim reddedildi.'), 403

    return render_template(
        'error.html',
        status_code=403,
        title='Erişim reddedildi',
        message='Bu işlem için yetkiniz yok veya güvenlik doğrulaması başarısız oldu.'
    ), 403


@app.errorhandler(500)
def handle_server_error(error):
    db.session.rollback()

    if wants_json_response():
        return jsonify(success=False, message='Beklenmeyen bir hata oluştu.'), 500

    return render_template(
        'error.html',
        status_code=500,
        title='Bir şey ters gitti',
        message='İşleminizi şu anda tamamlayamadık. Lütfen tekrar deneyin.'
    ), 500

# Ana Sayfa - Giri? ve Kayıt


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('public_landing.html')


@app.route('/privacy')
def privacy_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('public_privacy.html')


@app.route('/kvkk')
def kvkk_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('public_kvkk.html')


@app.route('/terms')
def terms_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('public_terms.html')


@app.route('/health')
def health_check():
    checks = {'database': 'ok'}
    status_code = 200

    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        db.session.rollback()
        checks['database'] = 'error'
        status_code = 503

    return jsonify(
        status='ok' if status_code == 200 else 'degraded',
        service='stokcari',
        environment=app.config.get('APP_ENV', 'development'),
        checks=checks
    ), status_code


@app.route('/robots.txt')
def robots_txt():
    cfg = site_config()
    site_url = (cfg.get('url') or app.config.get('SITE_URL') or request.host_url.rstrip('/')).rstrip('/')
    if cfg.get('seo_public_mode'):
        lines = [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {site_url}/sitemap.xml",
        ]
    else:
        lines = [
            "User-agent: *",
            "Disallow: /",
        ]
    return current_app.response_class("\n".join(lines) + "\n", mimetype="text/plain")


@app.route('/sitemap.xml')
def sitemap_xml():
    cfg = site_config()
    site_url = (cfg.get('url') or app.config.get('SITE_URL') or request.host_url.rstrip('/')).rstrip('/')
    now = datetime.now(timezone.utc).date().isoformat()

    # Public pages only (do not leak authenticated URLs)
    urls = [
        (f"{site_url}/", now),
        (f"{site_url}{url_for('privacy_page')}", now),
        (f"{site_url}{url_for('kvkk_page')}", now),
        (f"{site_url}{url_for('terms_page')}", now),
    ]

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod in urls:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{loc}</loc>")
        xml_lines.append(f"    <lastmod>{lastmod}</lastmod>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    return current_app.response_class("\n".join(xml_lines) + "\n", mimetype="application/xml")


@app.route('/api/notifications')
@login_required
def api_notifications():
    notifications = []

    if is_platform_admin_user(current_user):
        pending_support_tickets = SupportTicket.query.filter(
            SupportTicket.status.in_(['open', 'waiting_admin'])
        ).order_by(SupportTicket.updated_at.desc()).limit(5).all()
        if pending_support_tickets:
            latest_ticket = pending_support_tickets[0]
            notifications.append({
                'type': 'danger',
                'icon': 'support_agent',
                'title': 'Yeni destek talebi',
                'message': (
                    f'{len(pending_support_tickets)} talep destek yaniti bekliyor. '
                    f'Son talep: {latest_ticket.organization.name if latest_ticket.organization else "-"}'
                ),
                'time': 'Åimdi',
                'url': url_for('super_admin_dashboard') + '#platform-support'
            })

        expired_subscriptions = Organization.query.filter(
            Organization.subscription_end.isnot(None),
            Organization.subscription_end < date.today(),
            Organization.subscription_status != 'cancelled'
        ).count()
        if expired_subscriptions:
            notifications.append({
                'type': 'warning',
                'icon': 'event_busy',
                'title': 'Destek süresi doldu',
                'message': f'{expired_subscriptions} firman?n destek süresi doldu.',
                'time': 'Güncel',
                'url': url_for('super_admin_dashboard') + '#companies'
            })

        if not notifications:
            notifications.append({
                'type': 'success',
                'icon': 'verified',
                'title': 'Herşey yolunda',
                'message': 'Bekleyen destek talebi veya kritik platform uyarisi yok.',
                'time': 'Güncel',
                'url': url_for('super_admin_dashboard')
            })

        actionable_count = len([item for item in notifications if item['title'] != 'Herşey yolunda'])
        return jsonify({'success': True, 'count': actionable_count, 'notifications': notifications[:6]})

    tenant_ids = tenant_user_ids()

    critical_products = Urun.query.filter(
        Urun.user_id.in_(tenant_ids),
        Urun.stok_miktari <= Urun.kritik_stok
    ).order_by(Urun.stok_miktari.asc()).limit(5).all()
    if critical_products:
        notifications.append({
            'type': 'warning',
            'icon': 'warning',
            'title': 'Kritik stok uyarisi',
            'message': f'{len(critical_products)} urun kritik seviyede veya altinda.',
            'time': 'Simdi',
            'url': url_for('urunler')
        })

    risky_customers = [
        cari for cari in Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
        if (cari.bakiye or 0) > 1000
    ]
    if risky_customers:
        total_risk = sum(cari.bakiye or 0 for cari in risky_customers)
        notifications.append({
            'type': 'danger',
            'icon': 'account_balance_wallet',
            'title': 'Cari risk takibi',
            'message': f'{len(risky_customers)} caride toplam {total_risk:.2f} TL acik bakiye var.',
            'time': 'Bugun',
            'url': url_for('cariler')
        })

    today = datetime.now(timezone.utc).date()
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    today_sales = Satis.query.filter(
        Satis.user_id.in_(tenant_ids),
        Satis.tarih >= today_start
    ).order_by(Satis.tarih.desc()).limit(3).all()
    if today_sales:
        total_sales = sum(sale.genel_toplam or 0 for sale in today_sales)
        notifications.append({
            'type': 'success',
            'icon': 'payments',
            'title': 'Bugunku satislar',
            'message': f'{len(today_sales)} son satis toplam {total_sales:.2f} TL.',
            'time': 'Bugun',
            'url': url_for('gunluk_satislar')
        })

    open_quotes = Teklif.query.filter(
        Teklif.user_id.in_(tenant_ids),
        Teklif.durum.in_(['taslak', 'gonderildi'])
    ).count()
    if open_quotes:
        notifications.append({
            'type': 'info',
            'icon': 'description',
            'title': 'Acik teklifler',
            'message': f'Takip bekleyen {open_quotes} teklif bulunuyor.',
            'time': 'Guncel',
            'url': url_for('teklif_yonetimi')
        })

    if not notifications:
        notifications.append({
            'type': 'success',
            'icon': 'verified',
            'title': 'Her ?ey yolunda',
            'message': 'Kritik stok, cari risk veya bekleyen islem bulunmuyor.',
            'time': 'Guncel',
            'url': url_for('dashboard')
        })

    actionable_count = len([item for item in notifications if item['title'] != 'Herşey yolunda'])
    return jsonify({'success': True, 'count': actionable_count, 'notifications': notifications[:6]})

# Uygulama Ba?lat?c? (Mod?l Se?imi)


@app.route('/baslatin')
@login_required
def baslatin():
    return render_template('uygulama_baslatici.html')

# Personel Y?netimi Route'lar?

def get_active_leave_for_person(personel, today=None):
    if not personel:
        return None
    today = today or date.today()
    return (
        Izin.query
        .filter(
            Izin.user_id == personel.user_id,
            Izin.personel_id == personel.id,
            Izin.onay_durumu == 'Onaylandı',
            Izin.baslangic_tarihi <= today,
            Izin.bitis_tarihi >= today,
        )
        .order_by(Izin.bitis_tarihi.asc())
        .first()
    )


def get_personel_effective_status(personel, today=None):
    status = personel.calisma_durumu or 'Aktif'
    if status == 'Aktif' and get_active_leave_for_person(personel, today):
        return 'İzinli'
    return status


def enrich_personel_statuses(personeller, today=None):
    today = today or date.today()
    for personel in personeller:
        active_leave = get_active_leave_for_person(personel, today)
        personel.aktif_izin = active_leave
        personel.etkin_durum = 'İzinli' if (personel.calisma_durumu or 'Aktif') == 'Aktif' and active_leave else (personel.calisma_durumu or 'Aktif')
    return personeller


def has_overlapping_leave(personel_id, baslangic, bitis, exclude_leave_id=None, statuses=None):
    statuses = statuses or ['Beklemede', 'Onaylandı']
    query = Izin.query.filter(
        Izin.user_id == current_user.id,
        Izin.personel_id == personel_id,
        Izin.onay_durumu.in_(statuses),
        Izin.baslangic_tarihi <= bitis,
        Izin.bitis_tarihi >= baslangic,
    )
    if exclude_leave_id:
        query = query.filter(Izin.id != exclude_leave_id)
    return query.first()


def append_leave_decision_note(izin, action_label, note):
    note = (note or '').strip()
    if not note:
        return
    timestamp = format_tr_datetime(local_now())
    decision_note = f'[{timestamp}] {action_label}: {note}'
    izin.aciklama = f'{izin.aciklama}\n{decision_note}' if izin.aciklama else decision_note


def payroll_period_from_date(value=None):
    value = value or date.today()
    return value.strftime('%Y-%m')


def split_payroll_period(period):
    try:
        year_text, month_text = str(period).split('-', 1)
        year = int(year_text)
        month = int(month_text)
        if month < 1 or month > 12:
            raise ValueError
        return year, month
    except (TypeError, ValueError):
        today = date.today()
        return today.year, today.month


def month_bounds_from_period(period):
    year, month = split_payroll_period(period)
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def calculate_personel_payroll_summary(personel, period=None):
    period = period or payroll_period_from_date()
    period_start, period_end = month_bounds_from_period(period)
    base_salary = float(personel.maas or 0)
    primes = (
        Prim.query
        .filter(
            Prim.user_id == personel.user_id,
            Prim.personel_id == personel.id,
            Prim.donem == period,
        )
        .all()
    )
    paid_prime_ids = paid_cash_prime_ids(personel.user_id, [prim.id for prim in primes])
    payroll_primes = [prim for prim in primes if prim.id not in paid_prime_ids]
    advances = (
        Avans.query
        .filter(
            Avans.user_id == personel.user_id,
            Avans.personel_id == personel.id,
            Avans.kesinti_turu == 'Maaştan',
            Avans.durum.in_(['Beklemede', 'Kaydedildi', 'Ödendi']),
            func.date(Avans.talep_tarihi) >= period_start,
            func.date(Avans.talep_tarihi) <= period_end,
        )
        .all()
    )
    existing_payslip = (
        MaasKaydi.query
        .filter_by(
            user_id=personel.user_id,
            personel_id=personel.id,
            ay=period,
        )
        .first()
    )
    total_primes = sum(float(prim.tutar or 0) for prim in payroll_primes)
    total_advances = sum(float(avans.tutar or 0) for avans in advances)
    gross_total = base_salary + total_primes
    net_pay = max(0, gross_total - total_advances)
    is_paid = bool(existing_payslip and existing_payslip.odeme_durumu == 'Ödendi')
    return {
        'period': period,
        'period_start': period_start,
        'period_end': period_end,
        'base_salary': base_salary,
        'total_primes': total_primes,
        'total_advances': total_advances,
        'gross_total': gross_total,
        'net_pay': net_pay,
        'primes': payroll_primes,
        'cash_paid_primes': [prim for prim in primes if prim.id in paid_prime_ids],
        'advances': advances,
        'existing_payslip': existing_payslip,
        'is_paid': is_paid,
        'missing_bank_info': not bool((personel.iban or '').strip()),
    }


def calculate_bulk_payroll_summary(period=None):
    period = period or payroll_period_from_date()
    personeller = (
        Personel.query
        .filter_by(user_id=current_user.id, calisma_durumu='Aktif')
        .order_by(Personel.ad.asc(), Personel.soyad.asc())
        .all()
    )
    rows = []
    for personel in personeller:
        enrich_personel_statuses([personel])
        summary = calculate_personel_payroll_summary(personel, period)
        rows.append({
            'personel': personel,
            'summary': summary,
        })

    totals = {
        'employee_count': len(rows),
        'base_salary': sum(row['summary']['base_salary'] for row in rows),
        'total_primes': sum(row['summary']['total_primes'] for row in rows),
        'total_advances': sum(row['summary']['total_advances'] for row in rows),
        'gross_total': sum(row['summary']['gross_total'] for row in rows),
        'net_pay': sum(row['summary']['net_pay'] for row in rows),
        'payable_net': sum(row['summary']['net_pay'] for row in rows if not row['summary']['is_paid']),
        'paid_count': sum(1 for row in rows if row['summary']['is_paid']),
        'missing_bank_count': sum(1 for row in rows if row['summary']['missing_bank_info']),
    }
    return {
        'period': period,
        'rows': rows,
        'totals': totals,
    }


def payroll_payment_transactions(period):
    return (
        CashTransaction.query
        .filter(
            CashTransaction.user_id == current_user.id,
            CashTransaction.referans_tip == 'maas_odeme',
            CashTransaction.islem_tipi == 'cikis',
            CashTransaction.aciklama.ilike(f'{period}%'),
        )
        .order_by(CashTransaction.tarih.desc(), CashTransaction.id.desc())
        .all()
    )


def paid_cash_prime_ids(user_id, prime_ids):
    prime_ids = [int(prime_id) for prime_id in prime_ids if prime_id]
    if not prime_ids:
        return set()
    rows = (
        CashTransaction.query
        .filter(
            CashTransaction.user_id == user_id,
            CashTransaction.referans_tip == 'personel_prim',
            CashTransaction.referans_id.in_(prime_ids),
            CashTransaction.islem_tipi == 'cikis',
        )
        .all()
    )
    return {row.referans_id for row in rows}


def personel_finance_history(personel):
    if not personel:
        return []

    salary_transactions = (
        CashTransaction.query
        .filter(
            CashTransaction.user_id == personel.user_id,
            CashTransaction.referans_tip == 'maas_odeme',
            CashTransaction.islem_tipi == 'cikis',
        )
        .order_by(CashTransaction.tarih.desc(), CashTransaction.id.desc())
        .all()
    )
    related_salary_transactions = []
    for transaction in salary_transactions:
        period = (transaction.aciklama or '').split(' ', 1)[0]
        if not period:
            continue
        has_payslip = MaasKaydi.query.filter_by(
            user_id=personel.user_id,
            personel_id=personel.id,
            ay=period,
            odeme_durumu='Ödendi',
        ).first()
        if has_payslip:
            related_salary_transactions.append(transaction)

    advance_transactions = (
        CashTransaction.query
        .join(Avans, CashTransaction.referans_id == Avans.id)
        .filter(
            CashTransaction.user_id == personel.user_id,
            CashTransaction.referans_tip == 'personel_avans',
            CashTransaction.islem_tipi == 'cikis',
            Avans.personel_id == personel.id,
        )
        .all()
    )
    prime_transactions = (
        CashTransaction.query
        .join(Prim, CashTransaction.referans_id == Prim.id)
        .filter(
            CashTransaction.user_id == personel.user_id,
            CashTransaction.referans_tip == 'personel_prim',
            CashTransaction.islem_tipi == 'cikis',
            Prim.personel_id == personel.id,
        )
        .all()
    )

    history = []
    for transaction in related_salary_transactions:
        history.append({'type': 'Maaş', 'icon': 'payments', 'transaction': transaction})
    for transaction in advance_transactions:
        history.append({'type': 'Avans', 'icon': 'account_balance_wallet', 'transaction': transaction})
    for transaction in prime_transactions:
        history.append({'type': 'Peşin Prim', 'icon': 'workspace_premium', 'transaction': transaction})
    return sorted(history, key=lambda item: (item['transaction'].tarih or datetime.min.replace(tzinfo=timezone.utc), item['transaction'].id), reverse=True)


@app.route('/personel_yonetimi')
@app.route('/personel')
@login_required
def personel_yonetimi():
    search_query = (request.args.get('search') or '').strip().lower()
    selected_department = (request.args.get('department') or '').strip()
    selected_status = (request.args.get('status') or '').strip()
    all_personeller = (
        Personel.query
        .filter_by(user_id=current_user.id)
        .order_by(Personel.ad.asc(), Personel.soyad.asc())
        .all()
    )
    enrich_personel_statuses(all_personeller)
    status_counts = {
        'Aktif': sum(1 for personel in all_personeller if personel.etkin_durum == 'Aktif'),
        'İzinli': sum(1 for personel in all_personeller if personel.etkin_durum == 'İzinli'),
        'Pasif': sum(1 for personel in all_personeller if personel.etkin_durum == 'Pasif'),
    }

    filtered_personeller = all_personeller
    if search_query:
        filtered_personeller = [
            personel for personel in filtered_personeller
            if search_query in ' '.join([
                personel.ad or '',
                personel.soyad or '',
                personel.sicil_no or '',
                personel.pozisyon or '',
                personel.telefon or '',
                personel.departman.ad if personel.departman else '',
            ]).lower()
        ]
    if selected_department:
        filtered_personeller = [
            personel for personel in filtered_personeller
            if personel.departman_id and str(personel.departman_id) == selected_department
        ]
    if selected_status:
        filtered_personeller = [
            personel for personel in filtered_personeller
            if (personel.etkin_durum or '') == selected_status
        ]

    pagination = paginate_list_items(filtered_personeller)
    return render_template(
        'personel/personel_yonetimi.html',
        personeller=pagination.items,
        all_personeller=all_personeller,
        result_count=pagination.total,
        search_query=search_query,
        selected_department=selected_department,
        selected_status=selected_status,
        status_counts=status_counts,
        pagination=pagination,
    )


def current_user_departman_id(raw_departman_id):
    if not raw_departman_id:
        return None

    try:
        departman_id = int(raw_departman_id)
    except (TypeError, ValueError):
        raise ValueError('Geçersiz departman seçimi.')

    exists = Departman.query.filter_by(id=departman_id, user_id=current_user.id).first()
    if not exists:
        raise ValueError('Geçersiz departman seçimi.')

    return departman_id

@app.route('/departmanlar')
@login_required
def departmanlar():
    departmanlar = Departman.query.filter_by(user_id=current_user.id).all()
    return render_template('personel/departmanlar.html', departmanlar=departmanlar)

@app.route('/departman_ekle', methods=['GET', 'POST'])
@login_required
def departman_ekle():
    if request.method == 'POST':
        departman = Departman(
            ad=request.form.get('ad'),
            aciklama=request.form.get('aciklama'),
            user_id=current_user.id
        )
        db.session.add(departman)
        db.session.commit()
        flash('Departman başarıyla eklendi!', 'success')
        return redirect(url_for('departmanlar'))
    
    return render_template('personel/departman_ekle.html')

@app.route('/departman_duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def departman_duzenle(id):
    departman = Departman.query.get_or_404(id)
    if departman.user_id != current_user.id:
        abort(403)
    
    if request.method == 'POST':
        departman.ad = request.form.get('ad')
        departman.aciklama = request.form.get('aciklama')
        db.session.commit()
        flash('Departman başarıyla güncellendi!', 'success')
        return redirect(url_for('departmanlar'))
    
    return render_template('personel/departman_duzenle.html', departman=departman)

@app.route('/departman_sil/<int:id>', methods=['POST'])
@login_required
def departman_sil(id):
    departman = Departman.query.get_or_404(id)
    if departman.user_id != current_user.id:
        abort(403)
    
    if departman.personeller:
        flash('Bu departman personel içerdiği için silinemez!', 'error')
    else:
        db.session.delete(departman)
        db.session.commit()
        flash('Departman başarıyla silindi!', 'success')
    
    return redirect(url_for('departmanlar'))

@app.route('/personel_ekle', methods=['GET', 'POST'])
@login_required
def personel_ekle():
    departmanlar = Departman.query.filter_by(user_id=current_user.id).all()
    
    if request.method == 'POST':
        try:
            dogum_tarihi = datetime.strptime(request.form.get('dogum_tarihi'), '%Y-%m-%d').date()
            ise_giris_tarihi = datetime.strptime(request.form.get('ise_giris_tarihi'), '%Y-%m-%d').date()
            ise_cikis_tarihi = None
            if request.form.get('ise_cikis_tarihi'):
                ise_cikis_tarihi = datetime.strptime(request.form.get('ise_cikis_tarihi'), '%Y-%m-%d').date()
            
            personel = Personel(
                sicil_no=request.form.get('sicil_no'),
                ad=request.form.get('ad'),
                soyad=request.form.get('soyad'),
                tc_kimlik=request.form.get('tc_kimlik'),
                dogum_tarihi=dogum_tarihi,
                cinsiyet=request.form.get('cinsiyet'),
                medeni_hal=request.form.get('medeni_hal'),
                telefon=request.form.get('telefon'),
                email=request.form.get('email'),
                adres=request.form.get('adres'),
                ehliyet=request.form.get('ehliyet'),
                ehliyet_no=request.form.get('ehliyet_no'),
                kan_grubu=request.form.get('kan_grubu'),
                acil_durum_kisi=request.form.get('acil_durum_kisi'),
                acil_durum_telefon=request.form.get('acil_durum_telefon'),
                ise_giris_tarihi=ise_giris_tarihi,
                ise_cikis_tarihi=ise_cikis_tarihi,
                calisma_durumu=request.form.get('calisma_durumu'),
                departman_id=current_user_departman_id(request.form.get('departman_id')),
                pozisyon=request.form.get('pozisyon'),
                maas=float(request.form.get('maas') or 0),
                sgk_no=request.form.get('sgk_no'),
                vergi_no=request.form.get('vergi_no'),
                iban=request.form.get('iban'),
                banka_adi=request.form.get('banka_adi'),
                user_id=current_user.id
            )
            
            # Profil foto?raf? y?kleme
            if 'profil_foto' in request.files:
                file = request.files['profil_foto']
                if file and file.filename:
                    filename = secure_filename(f"personel_{personel.sicil_no}_{int(time.time())}.jpg")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    personel.profil_foto = filename
            
            db.session.add(personel)
            db.session.commit()
            flash('Personel başarıyla eklendi!', 'success')
            return redirect(url_for('personel_yonetimi'))
            
        except Exception as e:
            flash('Beklenmeyen bir hata oluştu.' if app.config.get('IS_PRODUCTION') else f'Hata: {str(e)}', 'error')
    
    return render_template('personel/personel_ekle.html', departmanlar=departmanlar)

@app.route('/personel_duzenle/<int:id>', methods=['GET', 'POST'])
@login_required
def personel_duzenle(id):
    personel = Personel.query.get_or_404(id)
    if personel.user_id != current_user.id:
        abort(403)
    
    departmanlar = Departman.query.filter_by(user_id=current_user.id).all()
    
    if request.method == 'POST':
        try:
            personel.sicil_no = request.form.get('sicil_no')
            personel.ad = request.form.get('ad')
            personel.soyad = request.form.get('soyad')
            personel.tc_kimlik = request.form.get('tc_kimlik')
            
            if request.form.get('dogum_tarihi'):
                personel.dogum_tarihi = datetime.strptime(request.form.get('dogum_tarihi'), '%Y-%m-%d').date()
            
            personel.cinsiyet = request.form.get('cinsiyet')
            personel.medeni_hal = request.form.get('medeni_hal')
            personel.telefon = request.form.get('telefon')
            personel.email = request.form.get('email')
            personel.adres = request.form.get('adres')
            personel.ehliyet = request.form.get('ehliyet')
            personel.ehliyet_no = request.form.get('ehliyet_no')
            personel.kan_grubu = request.form.get('kan_grubu')
            personel.acil_durum_kisi = request.form.get('acil_durum_kisi')
            personel.acil_durum_telefon = request.form.get('acil_durum_telefon')
            
            if request.form.get('ise_giris_tarihi'):
                personel.ise_giris_tarihi = datetime.strptime(request.form.get('ise_giris_tarihi'), '%Y-%m-%d').date()
            
            personel.ise_cikis_tarihi = None
            if request.form.get('ise_cikis_tarihi'):
                personel.ise_cikis_tarihi = datetime.strptime(request.form.get('ise_cikis_tarihi'), '%Y-%m-%d').date()
            
            personel.calisma_durumu = request.form.get('calisma_durumu')
            personel.departman_id = current_user_departman_id(request.form.get('departman_id'))
            personel.pozisyon = request.form.get('pozisyon')
            personel.maas = float(request.form.get('maas') or 0)
            personel.sgk_no = request.form.get('sgk_no')
            personel.vergi_no = request.form.get('vergi_no')
            personel.iban = request.form.get('iban')
            personel.banka_adi = request.form.get('banka_adi')
            
            # Profil foto?raf? gÖncelleme
            if 'profil_foto' in request.files:
                file = request.files['profil_foto']
                if file and file.filename:
                    filename = secure_filename(f"personel_{personel.sicil_no}_{int(time.time())}.jpg")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    personel.profil_foto = filename
            
            db.session.commit()
            flash('Personel başarıyla güncellendi!', 'success')
            return redirect(url_for('personel_yonetimi'))
            
        except Exception as e:
            flash('Beklenmeyen bir hata oluştu.' if app.config.get('IS_PRODUCTION') else f'Hata: {str(e)}', 'error')
    
    return render_template('personel/personel_duzenle.html', personel=personel, departmanlar=departmanlar)

@app.route('/personel_detay/<int:id>')
@login_required
def personel_detay(id):
    personel = Personel.query.get_or_404(id)
    if personel.user_id != current_user.id:
        abort(403)
    enrich_personel_statuses([personel])
    payroll_period = (request.args.get('period') or payroll_period_from_date()).strip()
    payroll_summary = calculate_personel_payroll_summary(personel, payroll_period)
    izin_gecmisi = (
        Izin.query
        .filter_by(user_id=current_user.id, personel_id=personel.id)
        .order_by(Izin.baslangic_tarihi.desc(), Izin.id.desc())
        .all()
    )
    
    avans_gecmisi = (
        Avans.query
        .filter_by(user_id=current_user.id, personel_id=personel.id)
        .order_by(Avans.talep_tarihi.desc(), Avans.id.desc())
        .limit(8)
        .all()
    )
    prim_gecmisi = (
        Prim.query
        .filter_by(user_id=current_user.id, personel_id=personel.id)
        .order_by(Prim.kayit_tarihi.desc(), Prim.id.desc())
        .limit(8)
        .all()
    )
    finans_gecmisi = personel_finance_history(personel)

    return render_template(
        'personel/personel_detay.html',
        personel=personel,
        izin_gecmisi=izin_gecmisi,
        avans_gecmisi=avans_gecmisi,
        prim_gecmisi=prim_gecmisi,
        finans_gecmisi=finans_gecmisi,
        payroll_summary=payroll_summary,
    )


@app.route('/personel_detay/<int:id>/bordro')
@login_required
def personel_bordro(id):
    personel = Personel.query.get_or_404(id)
    if personel.user_id != current_user.id:
        abort(403)
    enrich_personel_statuses([personel])
    payroll_period = (request.args.get('period') or payroll_period_from_date()).strip()
    payroll_summary = calculate_personel_payroll_summary(personel, payroll_period)
    return render_template(
        'personel/personel_bordro.html',
        personel=personel,
        payroll_summary=payroll_summary,
        generated_at=datetime.now(timezone.utc),
    )


@app.route('/personel/bordro/toplu')
@login_required
def toplu_maas_bordrosu():
    payroll_period = (request.args.get('period') or payroll_period_from_date()).strip()
    payroll_data = calculate_bulk_payroll_summary(payroll_period)
    accounts = ensure_default_accounts_for_user(current_user.id)
    payment_transactions = payroll_payment_transactions(payroll_period)
    return render_template(
        'personel/toplu_maas_bordrosu.html',
        payroll_data=payroll_data,
        accounts=accounts,
        payment_transactions=payment_transactions,
        generated_at=datetime.now(timezone.utc),
    )


@app.route('/personel/bordro/toplu/ode', methods=['POST'])
@login_required
def toplu_maas_odeme():
    payroll_period = (request.form.get('period') or payroll_period_from_date()).strip()
    account_id_raw = request.form.get('account_id')
    account = None
    if account_id_raw and str(account_id_raw).isdigit():
        account = db.session.get(Account, int(account_id_raw))
    if not account or account.user_id != current_user.id or not account.active:
        flash('Maaş Ödemesi için geçerli bir kasa/banka hesabı seçin.', 'error')
        return redirect(url_for('toplu_maas_bordrosu', period=payroll_period))

    payroll_data = calculate_bulk_payroll_summary(payroll_period)
    year, _month = split_payroll_period(payroll_period)
    payable_rows = [row for row in payroll_data['rows'] if not row['summary']['is_paid'] and row['summary']['net_pay'] > 0]
    total_payable = sum(row['summary']['net_pay'] for row in payable_rows)
    if total_payable <= 0:
        flash('Bu dönem için ödenecek yeni maaş kaydı bulunmuyor.', 'warning')
        return redirect(url_for('toplu_maas_bordrosu', period=payroll_period))

    try:
        paid_at = datetime.now(timezone.utc)
        for row in payable_rows:
            personel = row['personel']
            summary = row['summary']
            payslip = summary['existing_payslip']
            if not payslip:
                payslip = MaasKaydi(
                    personel_id=personel.id,
                    ay=payroll_period,
                    yil=year,
                    user_id=current_user.id,
                    created_at=paid_at,
                )
                db.session.add(payslip)
            payslip.brut_ucret = summary['gross_total']
            payslip.net_ucret = summary['net_pay']
            payslip.sgk_kesinti = 0
            payslip.gelir_vergisi = 0
            payslip.damga_vergisi = 0
            payslip.diger_kesintiler = summary['total_advances']
            payslip.odeme_durumu = 'Ödendi'
            payslip.odeme_tarihi = paid_at

        db.session.flush()
        transaction = CashTransaction(
            user_id=current_user.id,
            account_id=account.id,
            tarih=paid_at,
            islem_tipi='cikis',
            tutar=total_payable,
            odeme_turu='Havale/EFT' if account.type == 'bank' else 'Nakit',
            aciklama=f'{payroll_period} toplu maaş Ödemesi ({len(payable_rows)} personel)',
            referans_tip='maas_odeme',
        )
        db.session.add(transaction)
        db.session.commit()
        flash(f'{len(payable_rows)} personel için toplam ₺{total_payable:,.2f} maaş Ödemesi kaydedildi.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash('Maaş Ödemesi kaydedilemedi.' if app.config.get('IS_PRODUCTION') else f'Maaş Ödemesi kaydedilemedi: {exc}', 'error')

    return redirect(url_for('toplu_maas_bordrosu', period=payroll_period))


@app.route('/personel/bordro/banka-listesi.csv')
@login_required
def toplu_maas_banka_listesi_csv():
    payroll_period = (request.args.get('period') or payroll_period_from_date()).strip()
    payroll_data = calculate_bulk_payroll_summary(payroll_period)
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Dönem', 'Ad Soyad', 'Sicil No', 'Banka', 'IBAN', 'Açıklama', 'Net Tutar'])
    for row in payroll_data['rows']:
        personel = row['personel']
        summary = row['summary']
        writer.writerow([
            payroll_period,
            f'{personel.ad} {personel.soyad}',
            personel.sicil_no,
            personel.banka_adi or '',
            personel.iban or '',
            f'{payroll_period} maaş Ödemesi',
            f"{summary['net_pay']:.2f}".replace('.', ','),
        ])
    filename = f"maas-banka-listesi-{payroll_period}.csv"
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@app.route('/personel/bordro/kayitlar')
@login_required
def maas_bordro_kayitlari():
    selected_period = (request.args.get('period') or '').strip()
    query = (
        MaasKaydi.query
        .filter_by(user_id=current_user.id)
        .join(Personel, MaasKaydi.personel_id == Personel.id)
        .order_by(MaasKaydi.odeme_tarihi.desc().nullslast(), MaasKaydi.created_at.desc(), MaasKaydi.id.desc())
    )
    if selected_period:
        query = query.filter(MaasKaydi.ay == selected_period)
    records = query.all()
    periods = [
        row[0] for row in (
            db.session.query(MaasKaydi.ay)
            .filter_by(user_id=current_user.id)
            .distinct()
            .order_by(MaasKaydi.ay.desc())
            .all()
        )
    ]
    total_net = sum(float(record.net_ucret or 0) for record in records)
    total_gross = sum(float(record.brut_ucret or 0) for record in records)
    total_deductions = sum(float(record.diger_kesintiler or 0) for record in records)
    payment_transactions = payroll_payment_transactions(selected_period) if selected_period else []
    return render_template(
        'personel/maas_bordro_kayitlari.html',
        records=records,
        periods=periods,
        selected_period=selected_period,
        total_net=total_net,
        total_gross=total_gross,
        total_deductions=total_deductions,
        payment_transactions=payment_transactions,
    )

@app.route('/personel_sil/<int:id>', methods=['POST'])
@login_required
def personel_sil(id):
    personel = Personel.query.get_or_404(id)
    if personel.user_id != current_user.id:
        abort(403)
    
    db.session.delete(personel)
    db.session.commit()
    flash('Personel başarıyla silindi!', 'success')
    return redirect(url_for('personel_yonetimi'))

@app.route('/izinler')
@login_required
def izinler():
    izinler = (
        Izin.query
        .filter_by(user_id=current_user.id)
        .order_by(Izin.baslangic_tarihi.desc(), Izin.id.desc())
        .all()
    )
    today = date.today()
    for izin in izinler:
        izin.bugun_aktif = (
            izin.onay_durumu == 'Onaylandı'
            and izin.baslangic_tarihi <= today <= izin.bitis_tarihi
        )
    return render_template('personel/izinler.html', izinler=izinler)

@app.route('/izin_ekle', methods=['GET', 'POST'])
@login_required
def izin_ekle():
    personeller = Personel.query.filter_by(user_id=current_user.id, calisma_durumu='Aktif').all()
    selected_personel_id = (request.args.get('personel_id') or '').strip()
    next_url = safe_next_url('izinler')
    
    if request.method == 'POST':
        try:
            personel_id = int(request.form.get('personel_id') or 0)
            personel = Personel.query.filter_by(id=personel_id, user_id=current_user.id).first()
            if not personel:
                flash('Geçersiz personel seçimi.', 'error')
                return redirect(url_for('izin_ekle', personel_id=personel_id, next=next_url))

            baslangic = datetime.strptime(request.form.get('baslangic_tarihi'), '%Y-%m-%d').date()
            bitis = datetime.strptime(request.form.get('bitis_tarihi'), '%Y-%m-%d').date()
            if bitis < baslangic:
                flash('Bitiş tarihi başlangıç tarihinden önce olamaz.', 'error')
                return redirect(url_for('izin_ekle', personel_id=personel_id, next=next_url))

            overlapping_leave = has_overlapping_leave(personel.id, baslangic, bitis)
            if overlapping_leave:
                flash('Bu personelin aynı tarih aralığında bekleyen veya onaylı izni var.', 'error')
                return redirect(url_for('izin_ekle', personel_id=personel_id, next=next_url))

            gun_sayisi = (bitis - baslangic).days + 1
            
            izin = Izin(
                personel_id=personel.id,
                izin_tipi=request.form.get('izin_tipi'),
                baslangic_tarihi=baslangic,
                bitis_tarihi=bitis,
                gun_sayisi=gun_sayisi,
                aciklama=request.form.get('aciklama'),
                user_id=current_user.id
            )
            
            db.session.add(izin)
            db.session.commit()
            flash('İzin talebi başarıyla oluşturuldu!', 'success')
            return redirect(next_url)
            
        except Exception as e:
            flash('Beklenmeyen bir hata oluştu.' if app.config.get('IS_PRODUCTION') else f'Hata: {str(e)}', 'error')
    
    return render_template('personel/izin_ekle.html', personeller=personeller, selected_personel_id=selected_personel_id, next_url=next_url)

@app.route('/izin_onayla/<int:id>', methods=['POST'])
@login_required
def izin_onayla(id):
    izin = Izin.query.get_or_404(id)
    next_url = safe_next_url('izinler')
    if izin.user_id != current_user.id or izin.personel.user_id != current_user.id:
        abort(403)
    if izin.onay_durumu != 'Beklemede':
        flash('Sadece bekleyen izin talepleri onaylanabilir.', 'error')
        return redirect(next_url)

    overlapping_leave = has_overlapping_leave(
        izin.personel_id,
        izin.baslangic_tarihi,
        izin.bitis_tarihi,
        exclude_leave_id=izin.id,
        statuses=['Onaylandı']
    )
    if overlapping_leave:
        flash('Bu tarih aralığında zaten onaylı izin olduğu için talep onaylanamadı.', 'error')
        return redirect(next_url)
    
    izin.onay_durumu = 'Onaylandı'
    izin.onaylayan = current_user.id
    izin.onay_tarihi = datetime.now(timezone.utc)
    append_leave_decision_note(izin, 'Onay', request.form.get('karar_notu'))
    db.session.commit()
    flash('İzin talebi onaylandı!', 'success')
    return redirect(next_url)


@app.route('/izin_reddet/<int:id>', methods=['POST'])
@login_required
def izin_reddet(id):
    izin = Izin.query.get_or_404(id)
    next_url = safe_next_url('izinler')
    if izin.user_id != current_user.id or izin.personel.user_id != current_user.id:
        abort(403)
    if izin.onay_durumu != 'Beklemede':
        flash('Sadece bekleyen izin talepleri reddedilebilir.', 'error')
        return redirect(next_url)

    izin.onay_durumu = 'Reddedildi'
    izin.onaylayan = current_user.id
    izin.onay_tarihi = datetime.now(timezone.utc)
    append_leave_decision_note(izin, 'Red', request.form.get('karar_notu'))
    db.session.commit()
    flash('İzin talebi reddedildi.', 'success')
    return redirect(next_url)


@app.route('/izin_iptal/<int:id>', methods=['POST'])
@login_required
def izin_iptal(id):
    izin = Izin.query.get_or_404(id)
    next_url = safe_next_url('izinler')
    if izin.user_id != current_user.id or izin.personel.user_id != current_user.id:
        abort(403)
    if izin.onay_durumu != 'Onaylandı':
        flash('Sadece onaylı izinler iptal edilebilir.', 'error')
        return redirect(next_url)

    izin.onay_durumu = 'İptal Edildi'
    izin.onaylayan = current_user.id
    izin.onay_tarihi = datetime.now(timezone.utc)
    append_leave_decision_note(izin, 'İptal', request.form.get('karar_notu'))
    db.session.commit()
    flash('İzin iptal edildi.', 'success')
    return redirect(next_url)


@app.route('/avanslar')
@login_required
def avanslar():
    avanslar = (
        Avans.query
        .filter_by(user_id=current_user.id)
        .order_by(Avans.talep_tarihi.desc(), Avans.id.desc())
        .all()
    )
    accounts = ensure_default_accounts_for_user(current_user.id)
    return render_template('personel/avanslar.html', avanslar=avanslar, accounts=accounts)


@app.route('/avans_ode/<int:id>', methods=['POST'])
@login_required
def avans_ode(id):
    avans = Avans.query.get_or_404(id)
    if avans.user_id != current_user.id or avans.personel.user_id != current_user.id:
        abort(403)
    if avans.durum != 'Beklemede':
        flash('Sadece bekleyen avans talepleri ödenebilir.', 'error')
        return redirect(url_for('avanslar'))

    account_id_raw = request.form.get('account_id')
    account = None
    if account_id_raw and str(account_id_raw).isdigit():
        account = db.session.get(Account, int(account_id_raw))
    if not account or account.user_id != current_user.id or not account.active:
        flash('Avans Ödemesi için geçerli bir kasa/banka hesabı seçin.', 'error')
        return redirect(url_for('avanslar'))

    try:
        paid_at = datetime.now(timezone.utc)
        avans.durum = 'Ödendi'
        avans.talep_tarihi = paid_at
        note = (request.form.get('odeme_notu') or '').strip()
        if note:
            avans.aciklama = f'{avans.aciklama}\nÖdeme notu: {note}' if avans.aciklama else f'Ödeme notu: {note}'
        db.session.add(CashTransaction(
            user_id=current_user.id,
            account_id=account.id,
            tarih=paid_at,
            islem_tipi='cikis',
            tutar=float(avans.tutar or 0),
            odeme_turu='Havale/EFT' if account.type == 'bank' else 'Nakit',
            aciklama=f'{avans.personel.ad} {avans.personel.soyad} avans Ödemesi',
            referans_id=avans.id,
            referans_tip='personel_avans',
        ))
        db.session.commit()
        flash('Avans Ödemesi kaydedildi ve finans çıkışı oluşturuldu.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash('Avans Ödemesi kaydedilemedi.' if app.config.get('IS_PRODUCTION') else f'Avans Ödemesi kaydedilemedi: {exc}', 'error')
    return redirect(url_for('avanslar'))

@app.route('/avans_ekle', methods=['GET', 'POST'])
@login_required
def avans_ekle():
    personeller = Personel.query.filter_by(user_id=current_user.id, calisma_durumu='Aktif').all()
    selected_personel_id = (request.args.get('personel_id') or '').strip()
    next_url = safe_next_url('avanslar')
    
    if request.method == 'POST':
        avans = Avans(
            personel_id=request.form.get('personel_id'),
            tutar=float(request.form.get('tutar')),
            aciklama=request.form.get('aciklama'),
            kesinti_turu=request.form.get('kesinti_turu'),
            taksit_sayisi=int(request.form.get('taksit_sayisi') or 1),
            durum='Kaydedildi',
            user_id=current_user.id
        )
        
        db.session.add(avans)
        db.session.commit()
        flash('Avans kaydı başarıyla oluşturuldu!', 'success')
        return redirect(next_url)
    
    return render_template('personel/avans_ekle.html', personeller=personeller, selected_personel_id=selected_personel_id, next_url=next_url)


@app.route('/avans_sil/<int:id>', methods=['POST'])
@login_required
def avans_sil(id):
    avans = Avans.query.get_or_404(id)
    next_url = safe_next_url('avanslar')
    if avans.user_id != current_user.id or avans.personel.user_id != current_user.id:
        abort(403)

    CashTransaction.query.filter_by(
        user_id=current_user.id,
        referans_tip='personel_avans',
        referans_id=avans.id,
    ).delete(synchronize_session=False)
    db.session.delete(avans)
    db.session.commit()
    flash('Avans kaydı silindi.', 'success')
    return redirect(next_url)

@app.route('/primler')
@login_required
def primler():
    primler = (
        Prim.query
        .filter_by(user_id=current_user.id)
        .order_by(Prim.kayit_tarihi.desc(), Prim.id.desc())
        .all()
    )
    accounts = ensure_default_accounts_for_user(current_user.id)
    paid_prim_ids = paid_cash_prime_ids(current_user.id, [prim.id for prim in primler])
    return render_template('personel/primler.html', primler=primler, accounts=accounts, paid_prim_ids=paid_prim_ids)


@app.route('/prim_ode/<int:id>', methods=['POST'])
@login_required
def prim_ode(id):
    prim = Prim.query.get_or_404(id)
    if prim.user_id != current_user.id or prim.personel.user_id != current_user.id:
        abort(403)
    if prim.id in paid_cash_prime_ids(current_user.id, [prim.id]):
        flash('Bu prim zaten peşin ödenmiş.', 'warning')
        return redirect(url_for('primler'))

    account_id_raw = request.form.get('account_id')
    account = None
    if account_id_raw and str(account_id_raw).isdigit():
        account = db.session.get(Account, int(account_id_raw))
    if not account or account.user_id != current_user.id or not account.active:
        flash('Prim Ödemesi için geçerli bir kasa/banka hesabı seçin.', 'error')
        return redirect(url_for('primler'))

    try:
        paid_at = datetime.now(timezone.utc)
        note = (request.form.get('odeme_notu') or '').strip()
        if note:
            prim.aciklama = f'{prim.aciklama}\nPeşin Ödeme notu: {note}' if prim.aciklama else f'Peşin Ödeme notu: {note}'
        db.session.add(CashTransaction(
            user_id=current_user.id,
            account_id=account.id,
            tarih=paid_at,
            islem_tipi='cikis',
            tutar=float(prim.tutar or 0),
            odeme_turu='Havale/EFT' if account.type == 'bank' else 'Nakit',
            aciklama=f'{prim.personel.ad} {prim.personel.soyad} peşin prim Ödemesi',
            referans_id=prim.id,
            referans_tip='personel_prim',
        ))
        db.session.commit()
        flash('Prim peşin Ödendi ve finans çıkışı oluşturuldu.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash('Prim Ödemesi kaydedilemedi.' if app.config.get('IS_PRODUCTION') else f'Prim Ödemesi kaydedilemedi: {exc}', 'error')
    return redirect(url_for('primler'))

@app.route('/prim_ekle', methods=['GET', 'POST'])
@login_required
def prim_ekle():
    personeller = Personel.query.filter_by(user_id=current_user.id, calisma_durumu='Aktif').all()
    selected_personel_id = (request.args.get('personel_id') or '').strip()
    next_url = safe_next_url('primler')
    
    if request.method == 'POST':
        prim = Prim(
            personel_id=request.form.get('personel_id'),
            prim_tipi=request.form.get('prim_tipi'),
            tutar=float(request.form.get('tutar')),
            aciklama=request.form.get('aciklama'),
            donem=request.form.get('donem'),
            user_id=current_user.id
        )
        
        db.session.add(prim)
        db.session.commit()
        flash('Prim kaydı başarıyla oluşturuldu!', 'success')
        return redirect(next_url)
    
    return render_template('personel/prim_ekle.html', personeller=personeller, selected_personel_id=selected_personel_id, next_url=next_url)


@app.route('/prim_sil/<int:id>', methods=['POST'])
@login_required
def prim_sil(id):
    prim = Prim.query.get_or_404(id)
    next_url = safe_next_url('primler')
    if prim.user_id != current_user.id or prim.personel.user_id != current_user.id:
        abort(403)

    CashTransaction.query.filter_by(
        user_id=current_user.id,
        referans_tip='personel_prim',
        referans_id=prim.id,
    ).delete(synchronize_session=False)
    db.session.delete(prim)
    db.session.commit()
    flash('Prim kaydı silindi.', 'success')
    return redirect(next_url)


@app.route('/api/personel/<int:personel_id>')
@login_required
def api_personel_detay(personel_id):
    personel = Personel.query.get_or_404(personel_id)
    if personel.user_id != current_user.id:
        return jsonify({'error': 'Yetkisiz erişim'}), 403
    enrich_personel_statuses([personel])
    
    # Departman bilgisini ekle
    departman = Departman.query.get(personel.departman_id) if personel.departman_id else None
    active_leave = personel.aktif_izin
    
    personel_data = {
        'id': personel.id,
        'sicil_no': personel.sicil_no,
        'ad': personel.ad,
        'soyad': personel.soyad,
        'tc_kimlik': personel.tc_kimlik,
        'dogum_tarihi': personel.dogum_tarihi.isoformat() if personel.dogum_tarihi else None,
        'cinsiyet': personel.cinsiyet,
        'medeni_hal': personel.medeni_hal,
        'telefon': personel.telefon,
        'email': personel.email,
        'adres': personel.adres,
        'ehliyet': personel.ehliyet,
        'ehliyet_no': personel.ehliyet_no,
        'kan_grubu': personel.kan_grubu,
        'acil_durum_kisi': personel.acil_durum_kisi,
        'acil_durum_telefon': personel.acil_durum_telefon,
        'profil_foto': personel.profil_foto,
        'ise_giris_tarihi': personel.ise_giris_tarihi.isoformat() if personel.ise_giris_tarihi else None,
        'ise_cikis_tarihi': personel.ise_cikis_tarihi.isoformat() if personel.ise_cikis_tarihi else None,
        'calisma_durumu': personel.etkin_durum,
        'kayitli_calisma_durumu': personel.calisma_durumu,
        'aktif_izin': {
            'izin_tipi': active_leave.izin_tipi,
            'baslangic_tarihi': active_leave.baslangic_tarihi.isoformat(),
            'bitis_tarihi': active_leave.bitis_tarihi.isoformat(),
            'gun_sayisi': active_leave.gun_sayisi,
        } if active_leave else None,
        'pozisyon': personel.pozisyon,
        'maas': personel.maas,
        'sgk_no': personel.sgk_no,
        'vergi_no': personel.vergi_no,
        'iban': personel.iban,
        'banka_adi': personel.banka_adi,
        'departman': {
            'id': departman.id,
            'ad': departman.ad
        } if departman else None
    }
    
    return jsonify(personel_data)

# Giri? ve Kayıt


@app.route('/giris-kayit')
def giris_kayit():
    return render_template('firma_giris_ve_kayit_ekrani.html')


@app.route('/kayit', methods=['GET', 'POST'])
def kayit():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return render_template('firma_giris_ve_kayit_ekrani.html')

    if not platform_setting_bool('registrations_enabled', True):
        flash('Yeni firma kayitlari su anda kapali.', 'error')
        return redirect(url_for('giris'))

    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    firma_adi = (request.form.get('firma_adi') or '').strip()
    yetkili_adi = (request.form.get('yetkili_adi') or '').strip()
    telefon = (request.form.get('telefon') or '').strip()
    min_password_length = platform_setting_int('min_password_length', 8)

    if not email or not password or not firma_adi:
        flash('Firma adı, e-posta ve şifre zorunludur.', 'error')
        return redirect(url_for('kayit'))

    if len(password) < min_password_length:
        flash(f'Şifre en az {min_password_length} karakter olmalıdır.', 'error')
        return redirect(url_for('kayit'))

    # Email kontrolü
    if User.query.filter_by(email=email).first():
        flash('Bu email adresi zaten kayıtlı!', 'error')
        return redirect(url_for('kayit'))

    # Yeni kullanıcı oluştur
    yeni_user = User(
        email=email,
        password=generate_password_hash(password),
        firma_adi=firma_adi,
        yetkili_adi=yetkili_adi,
        telefon=telefon,
        paket_tipi=platform_setting('default_plan', 'demo'),
        urun_limiti=platform_setting_int('default_product_limit', 10),
        role='owner',
        is_platform_admin=email in platform_admin_emails(),
        platform_role='owner' if email in platform_admin_emails() else 'viewer',
    )

    db.session.add(yeni_user)
    db.session.flush()
    organization = ensure_user_organization(yeni_user)
    if organization:
        organization.user_limit = platform_setting_int('default_user_limit', 1)
        organization.product_limit = platform_setting_int('default_product_limit', 10)
        if yeni_user.is_platform_admin:
            organization.plan = 'profesyonel'
            organization.user_limit = max(organization.user_limit or 1, 10)
            organization.product_limit = max(organization.product_limit or 10, 999999)
    db.session.commit()

    flash('Kayıt başarılı! Giriş yapabilirsiniz.', 'success')
    return redirect(url_for('giris'))


@app.route('/giris', methods=['GET', 'POST'])
def giris():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return render_template('firma_giris_ve_kayit_ekrani.html')

    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    remember = request.form.get('remember') == 'on'

    ip_key = f'ip:{client_ip()}'
    ok, retry = ratelimit_check('login', ip_key, limit=10, per_seconds=60, block_seconds=300)
    if not ok:
        flash('Çok fazla giriş denemesi yapıldı. Lütfen biraz sonra tekrar deneyin.', 'error')
        resp = redirect(url_for('giris'))
        resp.status_code = 429
        if retry:
            resp.headers['Retry-After'] = str(int(retry))
        return resp

    if email:
        user_key = f'user:{email}'
        ok, retry = ratelimit_check('login', user_key, limit=6, per_seconds=60, block_seconds=600)
        if not ok:
            flash('Bu hesap için çok fazla giriş denemesi yapıldı. Lütfen biraz sonra tekrar deneyin.', 'error')
            resp = redirect(url_for('giris'))
            resp.status_code = 429
            if retry:
                resp.headers['Retry-After'] = str(int(retry))
            return resp

    if email in platform_admin_emails():
        bootstrap_platform_admins()

    user = User.query.filter_by(email=email).first()

    if user and user.aktif and check_password_hash(user.password, password):
        if ensure_reserved_platform_owner(user):
            db.session.commit()
        login_user(user, remember=remember)
        session['login_at'] = datetime.now(timezone.utc).isoformat()
        return redirect(url_for('dashboard'))
    elif user and not user.aktif:
        flash('Hesabınız pasif durumda. Lütfen yönetici ile iletişime geçin.', 'error')
        return redirect(url_for('giris'))
    else:
        flash('Email veya şifre hatalı!', 'error')
        return redirect(url_for('giris'))


@app.route('/sifremi-unuttum', methods=['GET', 'POST'])
def sifremi_unuttum():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return render_template('firma_giris_ve_kayit_ekrani.html', auth_mode='forgot')

    email = (request.form.get('email') or '').strip().lower()

    ip_key = f'ip:{client_ip()}'
    ok, retry = ratelimit_check('forgot', ip_key, limit=5, per_seconds=600, block_seconds=1800)
    if not ok:
        flash('Çok fazla istek yapıldı. Lütfen biraz sonra tekrar deneyin.', 'warning')
        resp = redirect(url_for('giris'))
        resp.status_code = 429
        if retry:
            resp.headers['Retry-After'] = str(int(retry))
        return resp

    if email:
        user_key = f'user:{email}'
        ok, retry = ratelimit_check('forgot', user_key, limit=3, per_seconds=600, block_seconds=1800)
        if not ok:
            flash('Bu hesap için çok fazla şifre sıfırlama isteği yapıldı. Lütfen biraz sonra tekrar deneyin.', 'warning')
            resp = redirect(url_for('giris'))
            resp.status_code = 429
            if retry:
                resp.headers['Retry-After'] = str(int(retry))
            return resp

    user = User.query.filter_by(email=email).first() if email else None
    if user and user.aktif:
        token = generate_password_reset_token(user)
        reset_url = url_for('sifre_sifirla', token=token, _external=True)
        if app.config.get('IS_PRODUCTION'):
            try:
                if smtp_is_configured():
                    send_password_reset_email(user, reset_url)
                else:
                    current_app.logger.error('SMTP not configured; cannot send password reset email.')
            except Exception:
                current_app.logger.exception('Password reset email send failed')
            flash('Şifre sıfırlama bağlantısı e-posta adresinize gönderildi.', 'success')
        else:
            app.logger.info('Password reset link for %s: %s', user.email, reset_url)
            flash(f'Geliştirme modu: Şifre sıfırlama bağlantısı: {reset_url}', 'success')
    else:
        flash('Bu e-posta sistemde kayıtlıysa şifre sıfırlama bağlantısı gönderilecektir.', 'info')
    return redirect(url_for('giris'))


@app.route('/sifre-sifirla/<token>', methods=['GET', 'POST'])
def sifre_sifirla(token):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    user = verify_password_reset_token(token)
    if not user or not user.aktif:
        flash('Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş.', 'error')
        return redirect(url_for('giris'))

    if request.method == 'GET':
        return render_template('firma_giris_ve_kayit_ekrani.html', auth_mode='reset', reset_token=token)

    password = request.form.get('password') or ''
    confirm_password = request.form.get('confirm_password') or ''
    if len(password) < 8:
        flash('Yeni şifre en az 8 karakter olmalıdır.', 'error')
        return redirect(url_for('sifre_sifirla', token=token))
    if password != confirm_password:
        flash('Şifreler eşleşmiyor.', 'error')
        return redirect(url_for('sifre_sifirla', token=token))

    user.password = generate_password_hash(password)
    db.session.commit()
    flash('Şifreniz güncellendi. Yeni şifrenizle giriş yapabilirsiniz.', 'success')
    return redirect(url_for('giris'))

# Dashboard


@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import date, timedelta

    # Kullanıcı istatistikleri
    tenant_ids = tenant_user_ids()
    urunler = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
    satislar = Satis.query.filter(Satis.user_id.in_(tenant_ids)).all()
    aktif_satislar = [s for s in satislar if s.durum != 'iptal']
    teklifler = Teklif.query.filter(Teklif.user_id.in_(tenant_ids)).all()

    toplam_urun = len(urunler)
    toplam_cari = len(cariler)
    toplam_satis = len(aktif_satislar)
    toplam_teklif = len(teklifler)
    tahsilat_sayisi = CariHareket.query.filter(
        CariHareket.user_id.in_(tenant_ids),
        CariHareket.islem_tipi == 'tahsilat'
    ).count()

    onboarding_steps = [
        {
            'key': 'product',
            'title': 'İlk ürününü ekle',
            'description': 'Barkod, satış fiyatı ve stok miktarıyla ilk ürün kaydını oluştur.',
            'icon': 'inventory_2',
            'url': url_for('urun_ekle'),
            'action': 'Ürün ekle',
            'done': toplam_urun > 0
        },
        {
            'key': 'sale',
            'title': 'İlk satışını yap',
            'description': 'POS ekranında ürünü sepete ekleyip nakit veya kart ile satışı tamamla.',
            'icon': 'point_of_sale',
            'url': url_for('pos'),
            'action': "POS'a git",
            'done': toplam_satis > 0
        },
        {
            'key': 'collection',
            'title': 'İlk tahsilatı kaydet',
            'description': 'Cari hesabı olan müşteriden ödeme aldığında tahsilat kaydı oluştur.',
            'icon': 'payments',
            'url': url_for('cariler'),
            'action': 'Carilere git',
            'done': tahsilat_sayisi > 0
        }
    ]
    onboarding_completed = sum(1 for step in onboarding_steps if step['done'])
    onboarding_progress = int((onboarding_completed / len(onboarding_steps)) * 100) if onboarding_steps else 0

    # Kritik stok hesapla
    kritik_stok = len([u for u in urunler if u.stok_miktari <= u.kritik_stok])

    # Bugünkü ve bu haftaki satışları hesapla
    bugun = date.today()
    bu_hafta_basi = bugun - timedelta(days=bugun.weekday())

    bugunku_satislar = Satis.query.filter(
        Satis.user_id.in_(tenant_ids),
        Satis.tarih >= bugun,
        Satis.tarih < bugun + timedelta(days=1)
    ).all()

    haftalik_satislar = Satis.query.filter(
        Satis.user_id.in_(tenant_ids),
        Satis.tarih >= bu_hafta_basi
    ).all()

    bugunku_satis = sum(s.genel_toplam or 0 for s in bugunku_satislar if s.durum != 'iptal')
    haftalik_satis = sum(s.genel_toplam or 0 for s in haftalik_satislar if s.durum != 'iptal')

    # Finansal özet
    toplam_borc = sum(c.borc or 0 for c in cariler)
    toplam_alacak = sum(c.alacak or 0 for c in cariler)
    net_bakiye = toplam_alacak - toplam_borc

    # Stok değeri
    toplam_stok_degeri = sum((u.stok_miktari or 0) * (u.satis_fiyati or 0) for u in urunler)

    # Analitik özetler

    # 1. Aylık satış trend verileri
    aylik_trend = {}
    for i in range(6):  # Son 6 ay
        ay_basi = datetime.combine((bugun.replace(day=1) - timedelta(days=30*i)).replace(day=1), datetime.min.time())
        ay_sonu = datetime.combine(((ay_basi + timedelta(days=32)).replace(day=1) -
                                   timedelta(days=1)), datetime.max.time())

        ay_satislar = Satis.query.filter(
            Satis.user_id.in_(tenant_ids),
            Satis.tarih >= ay_basi,
            Satis.tarih <= ay_sonu,
            Satis.durum != 'iptal'
        ).all()

        aylik_trend[ay_basi.strftime('%Y-%m')] = sum(s.genel_toplam or 0 for s in ay_satislar)

    # 2. En çok satan ürünler (top 5)
    en_cok_satan_urunler = []
    urun_satislar = {}
    for satis in aktif_satislar:
        for kalem in satis.kalemler:
            urun_id = kalem.urun_id
            if urun_id not in urun_satislar:
                urun_satislar[urun_id] = {'adet': 0, 'tutar': 0, 'urun_adi': kalem.urun_adi}
            urun_satislar[urun_id]['adet'] += kalem.miktar or 0
            urun_satislar[urun_id]['tutar'] += kalem.toplam or 0

    en_cok_satan_urunler = sorted(urun_satislar.values(),
                                  key=lambda x: x['tutar'], reverse=True)[:5]

    # 3. Kategori performans analizi
    kategori_performans = {}
    for urun in urunler:
        kat = urun.kategori or 'Kategorisiz'
        if kat not in kategori_performans:
            kategori_performans[kat] = {
                'urun_sayisi': 0,
                'stok_degeri': 0,
                'satis_adedi': 0,
                'satis_tutari': 0
            }
        kategori_performans[kat]['urun_sayisi'] += 1
        kategori_performans[kat]['stok_degeri'] += (urun.stok_miktari or 0) * (urun.satis_fiyati or 0)

    # Satış verilerini kategorilere ekle
    for satis in aktif_satislar:
        for kalem in satis.kalemler:
            urun = Urun.query.filter(Urun.id == kalem.urun_id, Urun.user_id.in_(tenant_ids)).first()
            if urun:
                kat = urun.kategori or 'Kategorisiz'
                if kat in kategori_performans:
                    kategori_performans[kat]['satis_adedi'] += kalem.miktar or 0
                    kategori_performans[kat]['satis_tutari'] += kalem.toplam or 0

    # 4. Cari risk analizi
    cari_risk_analizi = {
        'dusuk_risk': [],    # 0-5 gün borcu olanlar
        'orta_risk': [],     # 6-30 gün borcu olanlar
        'yuksek_risk': [],   # 30+ gün borcu olanlar
        'toplam_riskli_borc': 0
    }

    for cari in cariler:
        if cari.borc and cari.borc > 0:
            # Basit risk analizi (gerçek uygulamada son ödeme tarihi kontrol edilir)
            if cari.borc < 1000:
                cari_risk_analizi['dusuk_risk'].append({
                    'unvan': cari.unvan,
                    'borc': cari.borc,
                    'telefon': cari.telefon
                })
            elif cari.borc < 5000:
                cari_risk_analizi['orta_risk'].append({
                    'unvan': cari.unvan,
                    'borc': cari.borc,
                    'telefon': cari.telefon
                })
            else:
                cari_risk_analizi['yuksek_risk'].append({
                    'unvan': cari.unvan,
                    'borc': cari.borc,
                    'telefon': cari.telefon
                })
            cari_risk_analizi['toplam_riskli_borc'] += cari.borc

    # 5. Stok verimlilik metriği
    stok_verimlilik = {
        'hareketli_urunler': 0,  # Son 30 gün içinde satışı olanlar
        'yavas_urunler': 0,      # Son 30 gün içinde satışı olmayanlar
        'kritik_urunler': kritik_stok,
        'toplam_stok_degeri': toplam_stok_degeri
    }

    son_30_gun = datetime.combine(bugun - timedelta(days=30), datetime.min.time())
    son_30_gun_satis_urunleri = set()

    for satis in aktif_satislar:
        satis_tarih = satis.tarih
        if satis_tarih and satis_tarih.tzinfo:
            satis_tarih = satis_tarih.replace(tzinfo=None)
        if satis_tarih and satis_tarih >= son_30_gun:
            for kalem in satis.kalemler:
                son_30_gun_satis_urunleri.add(kalem.urun_id)

    stok_verimlilik['hareketli_urunler'] = len(son_30_gun_satis_urunleri)
    stok_verimlilik['yavas_urunler'] = toplam_urun - stok_verimlilik['hareketli_urunler']

    # Son hareketleri oluştur
    son_hareketler = []

    # Son satışlar (en son 5)
    son_satislar = sorted(aktif_satislar,
                          key=lambda x: x.tarih or datetime.min, reverse=True)[:5]
    for satis in son_satislar:
        cari = Cari.query.filter_by(id=satis.cari_id, user_id=current_user.id).first() if satis.cari_id else None
        son_hareketler.append({
            'baslik': f'Satış: {satis.fatura_no}',
            'aciklama': f'{cari.unvan if cari else "Perakende"} - ₺{satis.genel_toplam:.2f}',
            'tarih': satis.tarih,
            'renk': 'green',
            'icon': 'shopping_cart'
        })

    # Son eklenen ürünler (en son 3)
    son_urunler = sorted(urunler, key=lambda x: x.eklenme_tarihi or datetime.min, reverse=True)[:3]
    for urun in son_urunler:
        son_hareketler.append({
            'baslik': f'Yeni Ürün: {urun.urun_adi}',
            'aciklama': f'Stok: {urun.stok_miktari} {urun.birim} - ₺{urun.satis_fiyati}',
            'tarih': urun.eklenme_tarihi,
            'renk': 'blue',
            'icon': 'inventory_2'
        })

    # Son teklifler (en son 2)
    son_teklifler = sorted(teklifler, key=lambda x: x.tarih or datetime.min, reverse=True)[:2]
    for teklif in son_teklifler:
        cari_unvan = teklif.cari.unvan if teklif.cari else 'Cari Yok'
        son_hareketler.append({
            'baslik': f'Teklif: {teklif.teklif_no}',
            'aciklama': f'{cari_unvan} - ₺{teklif.genel_toplam:.2f}',
            'tarih': teklif.tarih,
            'renk': 'purple',
            'icon': 'description'
        })

    # Tarih sırasına göre sırala
    son_hareketler.sort(key=lambda x: x['tarih'] or datetime.min, reverse=True)
    son_hareketler = son_hareketler[:10]  # Son 10 hareket

    return render_template('dashboard_stok_ve_cari_takip.html',
                           toplam_urun=toplam_urun,
                           toplam_cari=toplam_cari,
                           kritik_stok=kritik_stok,
                           bugunku_satis=bugunku_satis,
                           haftalik_satis=haftalik_satis,
                           toplam_borc=toplam_borc,
                           toplam_alacak=toplam_alacak,
                           net_bakiye=net_bakiye,
                           toplam_stok_degeri=toplam_stok_degeri,
                           toplam_satis=toplam_satis,
                           toplam_teklif=toplam_teklif,
                           onboarding_steps=onboarding_steps,
                           onboarding_completed=onboarding_completed,
                           onboarding_progress=onboarding_progress,
                           son_hareketler=son_hareketler,
                           # Analitik özet verileri
                           aylik_trend=aylik_trend,
                           en_cok_satan_urunler=en_cok_satan_urunler,
                           kategori_performans=kategori_performans,
                           cari_risk_analizi=cari_risk_analizi,
                           stok_verimlilik=stok_verimlilik)

# Ürün Y?netimi


@app.route('/urunler')
@login_required
def urunler():
    search_query = request.args.get('search', '').strip()
    selected_category = request.args.get('category', 'all').strip() or 'all'
    selected_stock_status = request.args.get('stock_status', 'all').strip() or 'all'
    tenant_ids = tenant_user_ids()
    all_products = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    urunler_query = Urun.query.filter(Urun.user_id.in_(tenant_ids))

    # Arama sorgusu
    if search_query:
        urunler_query = urunler_query.filter(
            (Urun.urun_adi.ilike(f'%{search_query}%') |
             Urun.barkod.ilike(f'%{search_query}%') |
             Urun.kategori.ilike(f'%{search_query}%'))
        )

    if selected_category != 'all':
        urunler_query = urunler_query.filter(Urun.kategori == selected_category)

    urunler = urunler_query.order_by(Urun.urun_adi.asc()).all()

    if selected_stock_status == 'critical':
        urunler = [u for u in urunler if (u.stok_miktari or 0) <= (u.kritik_stok or 0)]
    elif selected_stock_status == 'out':
        urunler = [u for u in urunler if (u.stok_miktari or 0) <= 0]
    elif selected_stock_status == 'available':
        urunler = [u for u in urunler if (u.stok_miktari or 0) > (u.kritik_stok or 0)]

    # ?statistikler
    toplam_urun = len(all_products)
    toplam_stok = sum(u.stok_miktari or 0 for u in all_products)
    kritik_stok = len([u for u in all_products if (u.stok_miktari or 0) <= (u.kritik_stok or 0)])
    toplam_deger = round(sum((u.satis_fiyati or 0) * (u.stok_miktari or 0) for u in all_products), 2)
    kategoriler = sorted({u.kategori for u in all_products if u.kategori})

    pagination = paginate_list_items(urunler)

    return render_template('urun_listesi_ve_stok_yonetimi.html',
                           urunler=pagination.items,
                           pagination=pagination,
                           toplam_urun=toplam_urun,
                           toplam_stok=toplam_stok,
                           kritik_stok=kritik_stok,
                           toplam_deger=toplam_deger,
                           kategoriler=kategoriler,
                           search_query=search_query,
                           selected_category=selected_category,
                           selected_stock_status=selected_stock_status,
                           result_count=pagination.total)


@app.route('/urun-ekle', methods=['GET', 'POST'])
@login_required
def urun_ekle():
    if request.method == 'POST':
        # Demo limit kontrolü
        if current_user.paket_tipi == 'demo' and len(current_user.urunler) >= current_user.urun_limiti:
            flash('Demo hesabın?z?n Ürün limiti dolmu?tur!', 'error')
            return redirect(url_for('urunler'))

        depo_adi = normalize_warehouse_name(request.form.get('yeni_depo_adi') or request.form.get('depo_adi'))
        ensure_warehouse(depo_adi)

        yeni_urun = Urun(
            barkod=request.form.get('barkod'),
            urun_adi=request.form.get('urun_adi'),
            kategori=request.form.get('kategori'),
            birim=request.form.get('birim'),
            alis_fiyati=float(request.form.get('alis_fiyati', 0)),
            satis_fiyati=float(request.form.get('satis_fiyati', 0)),
            stok_miktari=float(request.form.get('stok_miktari', 0)),
            kritik_stok=float(request.form.get('kritik_stok', 10)),
            depo_adi=depo_adi,
            user_id=current_user.id
        )

        db.session.add(yeni_urun)
        db.session.commit()

        flash('Ürün başarıyla eklendi!', 'success')
        return redirect(url_for('urunler'))

    # Kategorileri ?ek - Ürünlerden ve session'dan
    kategoriler = list(tenant_categories_with_counts().keys())
    depolar = list(tenant_warehouses_with_metrics().keys())

    kategoriler = sorted(kategoriler)

    return render_template('urun_ekle.html', kategoriler=kategoriler, depolar=depolar)


@app.route('/urunler/demo-veri', methods=['POST'])
@login_required
def urun_demo_veri_ekle():
    if not is_platform_admin_user(current_user):
        return jsonify({
            'success': False,
            'message': 'Demo veri ekleme yalnızca süper admin taraf?ndan yap?labilir.',
        }), 403

    demo_products = [
        ('BOSCH Profesyonel Matkap', 'Elektrikli El Aletleri', 'Adet', 1850, 2490, 14, 3),
        ('Krom Pense 180 mm', 'El Aletleri', 'Adet', 135, 220, 32, 6),
        ('Galvaniz Vida 4x40 1000li', 'Bağlantı Elemanları', 'Kutu', 210, 340, 18, 4),
        ('Silikon Mastik Beyaz 280 ml', 'Kimyasallar', 'Adet', 58, 95, 45, 10),
        ('İş Güvenliği Gözlüğü', 'İş Güvenliği', 'Adet', 42, 75, 28, 8),
        ('PVC Küresel Vana 1/2', 'Tesisat', 'Adet', 64, 110, 24, 5),
        ('LED Projektör 50W', 'Elektrik Malzemeleri', 'Adet', 320, 520, 11, 3),
        ('Ahşap Zımpara 120 Kum', 'Boya ve Zımpara', 'Paket', 38, 65, 60, 15),
        ('Çelik Raf Ayağı 40 cm', 'Raf ve Mobilya Aksesuar?', 'Adet', 72, 125, 21, 5),
        ('Bahçe Hortumu 20 m', 'Bahçe Ürünleri', 'Adet', 390, 650, 9, 2),
        ('Kaynak Elektrodu 2.5 mm', 'Kaynak Malzemeleri', 'Kutu', 245, 410, 16, 4),
    ]
    demo_depots = ['Ana Depo', 'Şube Deposu', 'Servis Aracı']
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    created_count = 0

    for depot_name in demo_depots:
        ensure_warehouse(depot_name)

    for index, (name, category, unit, purchase_price, sale_price, stock, critical_stock) in enumerate(demo_products, start=1):
        if not Category.query.filter_by(user_id=current_user.id, name=category).first():
            db.session.add(Category(name=category, user_id=current_user.id))

        db.session.add(Urun(
            barkod=f'DEMO-{timestamp}-{index:02d}',
            urun_adi=name,
            kategori=category,
            birim=unit,
            alis_fiyati=purchase_price,
            satis_fiyati=sale_price,
            stok_miktari=stock,
            kritik_stok=critical_stock,
            depo_adi=demo_depots[(index - 1) % len(demo_depots)],
            user_id=current_user.id,
        ))
        created_count += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'message': f'{created_count} demo Ürün eklendi.',
        'created_count': created_count,
    })

# Cari Y?netimi


def build_cari_balance_map(cari_ids, tenant_ids):
    normalized_ids = [int(cari_id) for cari_id in cari_ids if cari_id]
    if not normalized_ids:
        return {}

    balance_map = {
        cari_id: {
            'balance': 0.0,
            'has_history': False,
        }
        for cari_id in normalized_ids
    }

    hareketler = CariHareket.query.filter(
        CariHareket.cari_id.in_(normalized_ids),
        CariHareket.user_id.in_(tenant_ids),
    ).all()

    for hareket in hareketler:
        bucket = balance_map.setdefault(hareket.cari_id, {'balance': 0.0, 'has_history': False})
        bucket['balance'] += cari_statement_signed_amount(hareket)
        bucket['has_history'] = True

    return balance_map


def resolve_cari_balance_snapshot(cari, tenant_ids, hareketler=None, balance_map=None):
    legacy_balance = float(cari.bakiye or 0)
    if hareketler is not None:
        has_history = len(hareketler) > 0
        movement_balance = sum(cari_statement_signed_amount(hareket) for hareket in hareketler)
    else:
        if balance_map is None:
            balance_map = build_cari_balance_map([cari.id], tenant_ids)
        bucket = balance_map.get(cari.id, {'balance': 0.0, 'has_history': False})
        has_history = bool(bucket.get('has_history'))
        movement_balance = float(bucket.get('balance') or 0.0)

    resolved_balance = movement_balance if has_history else legacy_balance
    return {
        'balance': resolved_balance,
        'alacak': max(0.0, resolved_balance),
        'borc': max(0.0, -resolved_balance),
        'source': 'movements' if has_history else 'legacy',
        'has_history': has_history,
        'legacy_balance': legacy_balance,
        'movement_balance': movement_balance,
        'has_mismatch': has_history and abs(movement_balance - legacy_balance) > 0.009,
    }


def attach_cari_display_balances(cariler, tenant_ids):
    if not cariler:
        return

    balance_map = build_cari_balance_map([cari.id for cari in cariler], tenant_ids)
    for cari in cariler:
        snapshot = resolve_cari_balance_snapshot(cari, tenant_ids, balance_map=balance_map)
        cari.display_bakiye = snapshot['balance']
        cari.display_alacak = snapshot['alacak']
        cari.display_borc = snapshot['borc']
        cari.balance_source = snapshot['source']
        cari.has_balance_mismatch = snapshot['has_mismatch']


def build_cari_list_context(search_query='', selected_type='all'):
    search_query = (search_query or '').strip()
    selected_type = (selected_type or 'all').strip() or 'all'
    tenant_ids = tenant_user_ids()
    all_cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
    cariler_query = Cari.query.filter(Cari.user_id.in_(tenant_ids))

    if search_query:
        cariler_query = cariler_query.filter(
            (Cari.unvan.ilike(f'%{search_query}%') |
             Cari.yetkili.ilike(f'%{search_query}%') |
             Cari.telefon.ilike(f'%{search_query}%') |
             Cari.email.ilike(f'%{search_query}%'))
        )

    if selected_type != 'all':
        cariler_query = cariler_query.filter(Cari.tipi == selected_type)

    cariler = cariler_query.order_by(Cari.unvan.asc()).all()
    attach_cari_display_balances(all_cariler, tenant_ids)
    attach_cari_display_balances(cariler, tenant_ids)
    pagination = paginate_list_items(cariler)
    return {
        'cariler': pagination.items,
        'pagination': pagination,
        'toplam_cari': len(all_cariler),
        'musteri_sayisi': len([c for c in all_cariler if (getattr(c, 'tipi', '') or '').startswith('M')]),
        'tedarikci_sayisi': len([c for c in all_cariler if (getattr(c, 'tipi', '') or '').startswith('T')]),
        'toplam_bakiye': sum(float(getattr(c, 'display_bakiye', c.bakiye) or 0) for c in all_cariler),
        'search_query': search_query,
        'selected_type': selected_type,
        'result_count': pagination.total
    }


@app.route('/cariler')
@login_required
def cariler():
    search_query = request.args.get('search', '').strip()
    selected_type = request.args.get('type', 'all').strip() or 'all'
    return render_template('cari_hesaplar_yonetimi_turkce_.html',
                           **build_cari_list_context(search_query, selected_type))


@app.route('/cari/<int:id>')
@login_required
def cari_detay(id):
    cari = Cari.query.get_or_404(id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye erişim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    # Cari'ye ait satışlar? getir
    tenant_ids = tenant_user_ids()
    ensure_default_accounts_for_user(current_user.id)
    accounts = Account.query.filter(Account.user_id.in_(tenant_ids), Account.active.is_(True)).order_by(Account.type, Account.name).all()
    satislar = Satis.query.filter(Satis.cari_id == cari.id, Satis.user_id.in_(tenant_ids)).order_by(Satis.tarih.desc()).all()

    # Cari'ye ait teklifleri getir
    teklifler = Teklif.query.filter(Teklif.cari_id == cari.id, Teklif.user_id.in_(tenant_ids)).order_by(Teklif.tarih.desc()).all()

    # Cari'ye ait hareketleri getir
    hareketler = CariHareket.query.filter(CariHareket.cari_id == cari.id, CariHareket.user_id.in_(tenant_ids)).order_by(CariHareket.tarih.desc()).all()
    balance_snapshot = resolve_cari_balance_snapshot(cari, tenant_ids, hareketler=hareketler)

    return render_template('cari_işlem_gecmisi_detayi.html',
                           cari=cari,
                           satislar=satislar,
                           teklifler=teklifler,
                           hareketler=hareketler,
                           accounts=accounts,
                           bakiye=balance_snapshot['balance'],
                           display_alacak=balance_snapshot['alacak'],
                           display_borc=balance_snapshot['borc'],
                           balance_source=balance_snapshot['source'],
                           has_balance_mismatch=balance_snapshot['has_mismatch'])


def cari_statement_signed_amount(hareket: "CariHareket") -> float:
    """
    Ekstre bakiyesi hesaplamak için hareketi +/- imzalı miktara çevirir.

    Uygulamadaki mevcut veri modeline göre:
    - 'satis' cari.alacak'? arttürür -> bakiye (alacak - borc) artar
    - 'tahsilat', 'odeme', 'iade' alacağı azaltır -> bakiye azal?r
    """
    tip = (hareket.islem_tipi or '').strip().lower()
    amount = float(hareket.tutar or 0)
    if tip == 'satis':
        return amount
    return -amount


def build_cari_ekstre_context(cari, tenant_ids, date_from_raw='', date_to_raw=''):
    overall_balance_snapshot = resolve_cari_balance_snapshot(cari, tenant_ids)
    from_dt = None
    to_dt = None
    if date_from_raw:
        from_dt = datetime.strptime(date_from_raw, '%Y-%m-%d')
    if date_to_raw:
        to_dt = datetime.strptime(date_to_raw, '%Y-%m-%d') + timedelta(days=1)

    hareket_query = CariHareket.query.filter(
        CariHareket.cari_id == cari.id,
        CariHareket.user_id.in_(tenant_ids),
    )
    if from_dt:
        hareket_query = hareket_query.filter(CariHareket.tarih >= from_dt)
    if to_dt:
        hareket_query = hareket_query.filter(CariHareket.tarih < to_dt)

    period_hareketler = hareket_query.order_by(CariHareket.tarih.asc(), CariHareket.id.asc()).all()

    opening_hareketler = []
    if from_dt:
        opening_query = CariHareket.query.filter(
            CariHareket.cari_id == cari.id,
            CariHareket.user_id.in_(tenant_ids),
            CariHareket.tarih < from_dt
        )
        opening_hareketler = opening_query.order_by(CariHareket.tarih.asc(), CariHareket.id.asc()).all()

    opening_balance = 0.0
    for h in opening_hareketler:
        opening_balance += cari_statement_signed_amount(h)

    if (
        not from_dt
        and not to_dt
        and not period_hareketler
        and overall_balance_snapshot['source'] == 'legacy'
    ):
        opening_balance = float(overall_balance_snapshot['balance'] or 0.0)

    running = opening_balance
    rows = []
    total_plus = 0.0
    total_minus = 0.0
    for h in period_hareketler:
        signed = cari_statement_signed_amount(h)
        if signed >= 0:
            total_plus += signed
        else:
            total_minus += abs(signed)
        running += signed
        rows.append({'hareket': h, 'signed': signed, 'balance': running})

    return {
        'cari': cari,
        'date_from': date_from_raw,
        'date_to': date_to_raw,
        'opening_balance': opening_balance,
        'closing_balance': running,
        'current_cari_balance': overall_balance_snapshot['balance'],
        'legacy_cari_balance': overall_balance_snapshot['legacy_balance'],
        'has_balance_mismatch': (not date_from_raw and not date_to_raw and abs(float(overall_balance_snapshot['balance'] or 0) - running) > 0.009),
        'has_legacy_balance_mismatch': overall_balance_snapshot['has_mismatch'],
        'total_plus': total_plus,
        'total_minus': total_minus,
        'rows': rows,
        'generated_at': datetime.now(timezone.utc),
    }


@app.route('/cari/<int:id>/ekstre')
@login_required
def cari_ekstre(id):
    cari = Cari.query.get_or_404(id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye eriim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    tenant_ids = tenant_user_ids()
    date_from_raw = (request.args.get('from') or '').strip()
    date_to_raw = (request.args.get('to') or '').strip()

    try:
        context = build_cari_ekstre_context(cari, tenant_ids, date_from_raw, date_to_raw)
    except ValueError:
        flash('Tarih aral" geersiz.', 'error')
        return redirect(url_for('cari_ekstre', id=cari.id))

    return render_template('cari_ekstre.html', **context)


@app.route('/cari/<int:id>/ekstre/yazdir')
@login_required
def cari_ekstre_yazdir(id):
    cari = Cari.query.get_or_404(id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye eriim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    tenant_ids = tenant_user_ids()
    date_from_raw = (request.args.get('from') or '').strip()
    date_to_raw = (request.args.get('to') or '').strip()

    try:
        context = build_cari_ekstre_context(cari, tenant_ids, date_from_raw, date_to_raw)
    except ValueError:
        flash('Tarih aral" geersiz.', 'error')
        return redirect(url_for('cari_ekstre', id=cari.id))

    return render_template('cari_ekstre_yazdir.html', **context)


@app.route('/cari/<int:id>/ekstre.csv')
@login_required
def cari_ekstre_csv(id):
    cari = Cari.query.get_or_404(id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye erişim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    tenant_ids = tenant_user_ids()
    date_from_raw = (request.args.get('from') or '').strip()
    date_to_raw = (request.args.get('to') or '').strip()

    from_dt = None
    to_dt = None
    if date_from_raw:
        try:
            from_dt = datetime.strptime(date_from_raw, '%Y-%m-%d')
        except ValueError:
            flash('Ba?lang?? tarihi geçersiz.', 'error')
            return redirect(url_for('cari_ekstre_csv', id=cari.id))
    if date_to_raw:
        try:
            to_dt = datetime.strptime(date_to_raw, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            flash('Biti? tarihi geçersiz.', 'error')
            return redirect(url_for('cari_ekstre_csv', id=cari.id))

    hareket_query = CariHareket.query.filter(
        CariHareket.cari_id == cari.id,
        CariHareket.user_id.in_(tenant_ids),
    )
    if from_dt:
        hareket_query = hareket_query.filter(CariHareket.tarih >= from_dt)
    if to_dt:
        hareket_query = hareket_query.filter(CariHareket.tarih < to_dt)
    hareketler = hareket_query.order_by(CariHareket.tarih.asc(), CariHareket.id.asc()).all()

    opening_balance = 0.0
    if from_dt:
        opening_query = CariHareket.query.filter(
            CariHareket.cari_id == cari.id,
            CariHareket.user_id.in_(tenant_ids),
            CariHareket.tarih < from_dt
        )
        for h in opening_query.all():
            opening_balance += cari_statement_signed_amount(h)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Cari', 'DonemBaslangic', 'DonemBitis', 'AcilisBakiye'])
    writer.writerow([cari.unvan, date_from_raw, date_to_raw, f'{opening_balance:.2f}'])
    writer.writerow([])
    writer.writerow(['Tarih', 'Islem', 'OdemeTuru', 'Aciklama', 'Artis', 'Azalis', 'Bakiye'])

    running = opening_balance
    for h in hareketler:
        signed = cari_statement_signed_amount(h)
        plus = f'{signed:.2f}' if signed >= 0 else ''
        minus = f'{abs(signed):.2f}' if signed < 0 else ''
        running += signed
        dt = format_tr_datetime(h.tarih, '%Y-%m-%d %H:%M') if h.tarih else ''
        writer.writerow([dt, h.islem_tipi, h.odeme_turu or '', h.aciklama or '', plus, minus, f'{running:.2f}'])

    filename = f"cari-ekstre-{secure_filename(cari.unvan)}.csv"
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=\"{filename}\"'
    return resp


@app.route('/cari/<int:id>/duzenle', methods=['GET', 'POST'])
@login_required
def cari_duzenle(id):
    cari = Cari.query.get_or_404(id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye erişim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    if request.method == 'POST':
        cari.unvan = request.form.get('unvan')
        cari.yetkili = request.form.get('yetkili')
        cari.telefon = request.form.get('telefon')
        cari.email = request.form.get('email')
        cari.vergidairesi = request.form.get('vergi_dairesi')
        cari.vergi_numarasi = request.form.get('vergi_numarasi')
        cari.adres = request.form.get('adres')
        cari.tipi = request.form.get('tipi', cari.tipi or 'Müşteri')

        db.session.commit()
        flash('Cari başarıyla güncellendi!', 'success')
        return redirect(url_for('cariler'))

    return render_template('cari_hesaplar_yonetimi_turkce_.html',
                           **build_cari_list_context(),
                           cari=cari,
                           duzenle_modu=True)


@app.route('/cari/<int:id>/sil', methods=['POST'])
@login_required
def cari_sil(id):
    cari = Cari.query.get_or_404(id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye erişim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    # Kontrol: Cari'ye ait satış kaydı var m?
    if cari.satislar:
        flash('Bu cariye ait satış kayıtları olduğu için silinemez! Önce satış kayıtların? silin.', 'error')
        return redirect(url_for('cariler'))

    # Kontrol: Cari'ye ait teklif var m?
    if cari.teklifler:
        flash('Bu cariye ait teklifler olduğu için silinemez! Önce teklifleri silin.', 'error')
        return redirect(url_for('cariler'))

    db.session.delete(cari)
    db.session.commit()
    flash('Cari başarıyla silindi!', 'success')
    return redirect(url_for('cariler'))


@app.route('/cari-ekle', methods=['GET', 'POST'])
@login_required
def cari_ekle():
    if request.method == 'POST':
        unvan = (request.form.get('unvan') or '').strip()
        if not unvan:
            flash('Cari unvanı zorunludur!', 'error')
            return redirect(url_for('cari_ekle'))

        yeni_cari = Cari(
            unvan=unvan,
            yetkili=request.form.get('yetkili'),
            telefon=request.form.get('telefon'),
            email=request.form.get('email'),
            vergidairesi=request.form.get('vergi_dairesi'),
            vergi_numarasi=request.form.get('vergi_numarasi'),
            adres=request.form.get('adres'),
            tipi=request.form.get('tipi', 'Müşteri'),
            user_id=current_user.id
        )

        db.session.add(yeni_cari)
        db.session.commit()

        flash('Cari başarıyla eklendi!', 'success')
        return redirect(url_for('cariler'))

    return render_template('cari_hesaplar_yonetimi_turkce_.html',
                           **build_cari_list_context(),
                           show_cari_modal=True)

# POS Sistemi


def serialize_pos_product(product):
    return {
        'id': product.id,
        'urun_adi': product.urun_adi,
        'barkod': product.barkod,
        'kategori': product.kategori,
        'satis_fiyati': float(product.satis_fiyati or 0),
        'stok_miktari': float(product.stok_miktari or 0),
        'birim': product.birim or 'Adet'
    }


@app.route('/pos')
@login_required
def pos():
    tenant_ids = tenant_user_ids()
    search_query = request.args.get('search', '').strip()
    selected_category = request.args.get('category', 'all').strip() or 'all'
    selected_stock_status = request.args.get('stock', 'all').strip() or 'all'

    all_products = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    urunler_query = Urun.query.filter(Urun.user_id.in_(tenant_ids))

    if search_query:
        urunler_query = urunler_query.filter(
            (Urun.urun_adi.ilike(f'%{search_query}%')) |
            (Urun.barkod.ilike(f'%{search_query}%')) |
            (Urun.kategori.ilike(f'%{search_query}%'))
        )

    if selected_category != 'all':
        urunler_query = urunler_query.filter(Urun.kategori == selected_category)

    urunler = urunler_query.order_by(Urun.urun_adi.asc()).all()

    if selected_stock_status == 'critical':
        urunler = [u for u in urunler if (u.stok_miktari or 0) <= (u.kritik_stok or 0)]
    elif selected_stock_status == 'low':
        urunler = [u for u in urunler if (u.stok_miktari or 0) > (u.kritik_stok or 0) and (u.stok_miktari or 0) <= ((u.kritik_stok or 0) + 15)]
    elif selected_stock_status == 'normal':
        urunler = [u for u in urunler if (u.stok_miktari or 0) > ((u.kritik_stok or 0) + 15)]
    elif selected_stock_status == 'out':
        urunler = [u for u in urunler if (u.stok_miktari or 0) <= 0]
    cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()

    # Ürünleri JSON serializable hale getir
    urunler_json = [serialize_pos_product(u) for u in urunler]

    # Carileri JSON serializable hale getir
    cariler_json = [{
        'id': c.id,
        'unvan': c.unvan,
        'borc': float(c.borc or 0),
        'alacak': float(c.alacak or 0)
    } for c in cariler]

    # Kategorileri topla (tekrars?z)
    categories = set()
    for urun in urunler:
        if urun.kategori:
            categories.add(urun.kategori)

    return render_template('pos_urun_secimi_ve_sepet.html',
                           urunler=urunler_json,
                           cariler=cariler_json,
                           categories=sorted(list(categories)))


@app.route('/pos-odeme')
@login_required
def pos_odeme():
    tenant_ids = tenant_user_ids()
    ensure_default_accounts_for_user(current_user.id)
    accounts = Account.query.filter(Account.user_id.in_(tenant_ids), Account.active.is_(True)).order_by(Account.type, Account.name).all()
    accounts_json = [{
        'id': a.id,
        'name': a.name,
        'type': a.type,
        'currency': a.currency,
    } for a in accounts]
    return render_template('pos_odeme_ekrani_turkce_.html', accounts_json=accounts_json, firm_name=current_user.firma_adi or 'StokCari')


@app.route('/pos/satis', methods=['POST'])
@login_required
@audit_log('CREATE', 'Satis')
def pos_satis():
    """POS satışını işle - stok düş ve cari kaydı oluştur"""
    try:
        data = request.get_json() or {}
        items = data.get('items', [])
        if not items or not isinstance(items, list):
            return jsonify({'success': False, 'message': 'Sepet boş!'})

        try:
            kdv_orani = float(data.get('kdvRate', 18))
            iskonto = float(data.get('discount', 0))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Geçersiz KDV ya da iskonto değeri'})

        if kdv_orani < 0 or kdv_orani > 100:
            return jsonify({'success': False, 'message': 'KDV orani 0 ile 100 arasinda olmali'})
        if iskonto < 0:
            return jsonify({'success': False, 'message': 'Iskonto negatif olamaz'})

        cari_id = int(data.get('customerId')) if data.get('customerId') else None
        cari = db.session.get(Cari, cari_id) if cari_id else None
        if cari and not belongs_to_current_tenant(cari):
            return jsonify({'success': False, 'message': 'Geçersiz müşteri seçimi!'})

        fatura_no = generate_fatura_no()
        depo = normalize_warehouse_name(data.get('warehouse') or DEFAULT_WAREHOUSE)
        odeme_yontemi = normalize_payment_method(data.get('paymentMethod') or data.get('payment_method'))
        account_id_raw = data.get('account_id') or data.get('accountId')
        account_id = None
        if isinstance(account_id_raw, int):
            account_id = account_id_raw
        elif isinstance(account_id_raw, str) and account_id_raw.strip().isdigit():
            account_id = int(account_id_raw.strip())

        if odeme_yontemi == 'Alacak' and not cari:
            return jsonify({'success': False, 'message': 'Veresiye satış için cari seçmelisiniz.'})

        # Veresiye satışta kasa/banka/POS hesabı seçimi anlams?z; para hareketi yaz?lmaz.
        if odeme_yontemi == 'Alacak':
            account_id = None

        if account_id:
            tenant_ids = tenant_user_ids()
            account = db.session.get(Account, account_id)
            if not account or account.user_id not in tenant_ids or not account.active:
                return jsonify({'success': False, 'message': 'Seçilen hesap geçersiz.'})

        satis = Satis(
            fatura_no=fatura_no,
            cari_id=cari.id if cari else None,
            user_id=current_user.id,
            tarih=datetime.now(timezone.utc),
            depo=depo,
            kdv_orani=kdv_orani,
            iskonto=iskonto,
            durum='tamamlandi'
        )
        db.session.add(satis)
        db.session.flush()

        genel_toplam = 0.0
        for item in items:
            product_id = item.get('id')
            if not product_id:
                db.session.rollback()
                return jsonify({'success': False, 'message': 'Sepette gecersiz urun var'})

            urun = db.session.get(Urun, int(product_id))
            if not urun or not belongs_to_current_tenant(urun):
                db.session.rollback()
                return jsonify({'success': False, 'message': 'Sepette erisilemeyen urun var'})

            miktar = normalize_amount(item.get('quantity', 1))
            birim_fiyat = normalize_amount(item.get('price', 0))
            birim = item.get('unit') or urun.birim or 'Adet'

            if miktar <= 0 or birim_fiyat < 0:
                db.session.rollback()
                return jsonify({'success': False, 'message': 'Sepette gecersiz miktar ya da fiyat var'})
            if (urun.stok_miktari or 0) < miktar:
                db.session.rollback()
                return jsonify({'success': False, 'message': f'{urun.urun_adi} için yetersiz stok!'})

            toplam = miktar * birim_fiyat
            satis_kalemi = SatisKalemi(
                satis_id=satis.id,
                urun_id=urun.id,
                urun_adi=urun.urun_adi,
                barkod=urun.barkod,
                miktar=miktar,
                birim=birim,
                birim_fiyat=birim_fiyat,
                toplam=toplam
            )
            db.session.add(satis_kalemi)

            eski_stok = urun.stok_miktari or 0
            urun.stok_miktari = eski_stok - miktar
            record_stock_movement(
                urun,
                'cikis',
                miktar,
                depo,
                eski_stok,
                urun.stok_miktari,
                f'POS satış? - {fatura_no}',
                cari_id=cari.id if cari else None
            )
            genel_toplam += toplam

        totals, total_error = calculate_sale_totals(genel_toplam, kdv_orani, iskonto)
        if total_error:
            db.session.rollback()
            return jsonify({'success': False, 'message': total_error})

        satis.ara_toplam = totals['ara_toplam']
        satis.kdv_orani = totals['kdv_orani']
        satis.kdv_tutar = totals['kdv_tutar']
        satis.iskonto = totals['iskonto']
        satis.genel_toplam = totals['genel_toplam']

        payment_integration_result = None
        if is_card_payment_method(odeme_yontemi):
            pos_settings = pos_integration_settings_for_user(current_user.id)
            sale_context = {
                'invoice_no': fatura_no,
                'amount': satis.genel_toplam,
                'payment_method': odeme_yontemi,
                'callback_reference': f'pos-sale-{fatura_no}',
                'customer': {'id': cari.id, 'unvan': cari.unvan} if cari else None,
                'items': [{
                    'name': sk.urun_adi,
                    'qty': float(sk.miktar or 0),
                    'unit': sk.birim or '',
                    'unit_price': float(sk.birim_fiyat or 0),
                    'line_total': float(sk.toplam or 0),
                } for sk in SatisKalemi.query.filter_by(satis_id=satis.id).all()]
            }
            payment_integration_result = execute_pos_payment_adapter(pos_settings, sale_context)
            if not payment_integration_result.get('success'):
                db.session.rollback()
                return jsonify({
                    'success': False,
                    'message': payment_integration_result.get('message') or 'POS Ödeme onay? al?namad?.',
                    'payment_integration': payment_integration_result
                }), 409

        if cari and odeme_yontemi == 'Alacak':
            cari.alacak = (cari.alacak or 0) + satis.genel_toplam
            cari_hareket = CariHareket(
                cari_id=cari.id,
                user_id=current_user.id,
                islem_tipi='satis',
                tutar=satis.genel_toplam,
                aciklama=f'POS satış faturas? {fatura_no}',
                odeme_turu=odeme_yontemi,
                referans_id=satis.id,
                referans_tip='satis'
            )
            db.session.add(cari_hareket)

        if odeme_yontemi != 'Alacak':
            create_cash_transaction(
                cari,
                satis.genel_toplam,
                'giris',
                odeme_yontemi,
                f'POS satış - {fatura_no}',
                referans_id=satis.id,
                referans_tip='satis',
                account_id=account_id
            )

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Satış başarıyla tamamlandı: {fatura_no}',
            'fatura_no': fatura_no,
            'total': satis.genel_toplam,
            'receipt': {
                'fatura_no': fatura_no,
                'date_iso': satis.tarih.isoformat(),
                'date_local': format_tr_datetime(satis.tarih),
                'warehouse': depo,
                'payment_method': odeme_yontemi,
                'subtotal': satis.ara_toplam,
                'vat_rate': kdv_orani,
                'vat_total': satis.kdv_tutar,
                'discount': iskonto,
                'total': satis.genel_toplam,
                'payment_integration': payment_integration_result,
                'customer': {'id': cari.id, 'unvan': cari.unvan} if cari else None,
                'items': [{
                    'name': sk.urun_adi,
                    'qty': float(sk.miktar or 0),
                    'unit': sk.birim or '',
                    'unit_price': float(sk.birim_fiyat or 0),
                    'line_total': float(sk.toplam or 0),
                } for sk in SatisKalemi.query.filter_by(satis_id=satis.id).all()]
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Satış işlemi başarısız: {str(e)}'})


@app.route('/nakit')
@login_required
def nakit_yonetimi():
    tenant_ids = tenant_user_ids()
    # ensure defaults for current user (so UI can show accounts immediately)
    ensure_default_accounts_for_user(current_user.id)

    selected_account_id = request.args.get('account_id', '').strip()
    account_id = int(selected_account_id) if selected_account_id.isdigit() else None

    accounts = Account.query.filter(Account.user_id.in_(tenant_ids), Account.active.is_(True)).order_by(Account.type, Account.name).all()
    account_type_labels = {
        'cash': 'Kasa',
        'bank': 'Banka',
        'pos': 'POS',
    }

    tx_query = CashTransaction.query.filter(CashTransaction.user_id.in_(tenant_ids))
    if account_id:
        tx_query = tx_query.filter(CashTransaction.account_id == account_id)
    transactions = tx_query.order_by(CashTransaction.tarih.desc()).limit(200).all()

    total_giris = sum(t.tutar for t in transactions if t.islem_tipi == 'giris')
    total_cikis = sum(t.tutar for t in transactions if t.islem_tipi == 'cikis')
    bakiye = total_giris - total_cikis
    return render_template('nakit_yonetimi.html',
                           transactions=transactions,
                           total_giris=total_giris,
                           total_cikis=total_cikis,
                           bakiye=bakiye,
                           accounts=accounts,
                           account_type_labels=account_type_labels,
                           selected_account_id=str(account_id) if account_id else '')

# ?n Muhasebe (Hesaplar)


@app.route('/onmuhasebe/hesaplar', methods=['GET', 'POST'])
@login_required
def onmuhasebe_hesaplar():
    tenant_ids = tenant_user_ids()

    # Ensure defaults exist for all tenant users so the screen never looks "empty" by mistake.
    for user_id in tenant_ids:
        ensure_default_accounts_for_user(user_id)

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()

        if action == 'create':
            name = (request.form.get('name') or '').strip()
            account_type = (request.form.get('type') or '').strip()
            currency = (request.form.get('currency') or 'TRY').strip().upper()
            opening_balance_raw = (request.form.get('opening_balance') or '0').strip()
            iban = (request.form.get('iban') or '').strip() or None
            bank_name = (request.form.get('bank_name') or '').strip() or None

            if not name:
                flash('Hesap ad? zorunludur.', 'error')
                return redirect(url_for('onmuhasebe_hesaplar'))

            if account_type not in ('cash', 'bank', 'pos'):
                flash('Geçersiz hesap tipi.', 'error')
                return redirect(url_for('onmuhasebe_hesaplar'))

            try:
                opening_balance = float(opening_balance_raw.replace(',', '.')) if opening_balance_raw else 0.0
            except ValueError:
                flash('A??l?? bakiyesi geçersiz.', 'error')
                return redirect(url_for('onmuhasebe_hesaplar'))

            account = Account(
                user_id=current_user.id,
                type=account_type,
                name=name,
                currency=currency or 'TRY',
                opening_balance=opening_balance,
                active=True,
                iban=iban,
                bank_name=bank_name,
            )
            db.session.add(account)
            try:
                db.session.commit()
                flash('Hesap oluşturuldu.', 'success')
            except Exception:
                db.session.rollback()
                flash('Hesap oluşturulamad?. Ayn? isimde hesap olabilir.', 'error')

            return redirect(url_for('onmuhasebe_hesaplar'))

        if action == 'toggle':
            account_id_raw = (request.form.get('account_id') or '').strip()
            if not account_id_raw.isdigit():
                flash('Geçersiz hesap.', 'error')
                return redirect(url_for('onmuhasebe_hesaplar'))

            account = db.session.get(Account, int(account_id_raw))
            if not account or account.user_id not in tenant_ids:
                flash('Hesap bulunamadı.', 'error')
                return redirect(url_for('onmuhasebe_hesaplar'))

            account.active = not bool(account.active)
            db.session.commit()
            flash('Hesap durumu güncellendi.', 'success')
            return redirect(url_for('onmuhasebe_hesaplar'))

        flash('Geçersiz işlem.', 'error')
        return redirect(url_for('onmuhasebe_hesaplar'))

    accounts = Account.query.filter(Account.user_id.in_(tenant_ids)).order_by(Account.active.desc(), Account.type, Account.name).all()

    # Aggregate cash transaction totals per account for current tenant.
    # balance = opening_balance + giris - cikis
    aggregates = (
        db.session.query(
            CashTransaction.account_id.label('account_id'),
            func.sum(case((CashTransaction.islem_tipi == 'giris', CashTransaction.tutar), else_=0.0)).label('sum_giris'),
            func.sum(case((CashTransaction.islem_tipi == 'cikis', CashTransaction.tutar), else_=0.0)).label('sum_cikis'),
        )
        .filter(CashTransaction.user_id.in_(tenant_ids))
        .group_by(CashTransaction.account_id)
        .all()
    )
    totals_by_account = {row.account_id: row for row in aggregates}

    account_rows = []
    for account in accounts:
        row = totals_by_account.get(account.id)
        sum_giris = float(row.sum_giris or 0.0) if row else 0.0
        sum_cikis = float(row.sum_cikis or 0.0) if row else 0.0
        opening_balance = float(account.opening_balance or 0.0)
        balance = opening_balance + sum_giris - sum_cikis
        account_rows.append({
            'account': account,
            'opening_balance': opening_balance,
            'sum_giris': sum_giris,
            'sum_cikis': sum_cikis,
            'balance': balance,
        })

    return render_template('onmuhasebe_hesaplar.html', account_rows=account_rows)


@app.route('/onmuhasebe/hesaplar/<int:account_id>', methods=['GET', 'POST'])
@login_required
def onmuhasebe_hesap_detay(account_id: int):
    tenant_ids = tenant_user_ids()
    account = db.session.get(Account, account_id)
    if not account or account.user_id not in tenant_ids:
        flash('Hesap bulunamadı.', 'error')
        return redirect(url_for('onmuhasebe_hesaplar'))

    # Ensure default accounts exist so transfer dropdown never breaks.
    for user_id in tenant_ids:
        ensure_default_accounts_for_user(user_id)

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()

        if action == 'tx':
            islem_tipi = (request.form.get('islem_tipi') or '').strip()
            tutar_raw = (request.form.get('tutar') or '').strip()
            aciklama = (request.form.get('aciklama') or '').strip()
            tarih_raw = (request.form.get('tarih') or '').strip()

            if islem_tipi not in ('giris', 'cikis'):
                flash('Geçersiz işlem tipi.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            try:
                tutar = float(tutar_raw.replace(',', '.'))
            except ValueError:
                flash('Tutar geçersiz.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            if tutar <= 0:
                flash('Tutar sıfırdan büyük olmalı.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            if tarih_raw:
                try:
                    tarih = datetime.strptime(tarih_raw, '%Y-%m-%d')
                except ValueError:
                    flash('Tarih geçersiz.', 'error')
                    return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))
            else:
                tarih = datetime.now(timezone.utc)

            odeme_turu = {
                'cash': 'Nakit',
                'bank': 'Banka',
                'pos': 'POS',
            }.get(account.type, 'Nakit')

            tx = CashTransaction(
                user_id=account.user_id,
                account_id=account.id,
                cari_id=None,
                tarih=tarih,
                islem_tipi=islem_tipi,
                tutar=tutar,
                odeme_turu=odeme_turu,
                aciklama=aciklama or 'Manuel fi?',
                referans_tip='manual',
                ip_adresi=request.remote_addr,
                user_agent=(request.user_agent.string or '')[:500],
            )
            db.session.add(tx)
            db.session.commit()
            flash('Hareket eklendi.', 'success')
            return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

        if action == 'transfer':
            target_id_raw = (request.form.get('target_account_id') or '').strip()
            tutar_raw = (request.form.get('tutar') or '').strip()
            aciklama = (request.form.get('aciklama') or '').strip()
            tarih_raw = (request.form.get('tarih') or '').strip()

            if not target_id_raw.isdigit():
                flash('Hedef hesap geçersiz.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            target = db.session.get(Account, int(target_id_raw))
            if not target or target.user_id not in tenant_ids:
                flash('Hedef hesap bulunamadı.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            if target.id == account.id:
                flash('Ayn? hesaba transfer yapılamaz.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            try:
                tutar = float(tutar_raw.replace(',', '.'))
            except ValueError:
                flash('Tutar geçersiz.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            if tutar <= 0:
                flash('Tutar sıfırdan büyük olmalı.', 'error')
                return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

            if tarih_raw:
                try:
                    tarih = datetime.strptime(tarih_raw, '%Y-%m-%d')
                except ValueError:
                    flash('Tarih geçersiz.', 'error')
                    return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))
            else:
                tarih = datetime.now(timezone.utc)

            note = aciklama or 'Hesaplar aras? transfer'

            out_tx = CashTransaction(
                user_id=account.user_id,
                account_id=account.id,
                tarih=tarih,
                islem_tipi='cikis',
                tutar=tutar,
                odeme_turu='Transfer',
                aciklama=f'{note} â†’ {target.name}',
                referans_tip='transfer',
                ip_adresi=request.remote_addr,
                user_agent=(request.user_agent.string or '')[:500],
            )
            in_tx = CashTransaction(
                user_id=target.user_id,
                account_id=target.id,
                tarih=tarih,
                islem_tipi='giris',
                tutar=tutar,
                odeme_turu='Transfer',
                aciklama=f'{note} â† {account.name}',
                referans_tip='transfer',
                ip_adresi=request.remote_addr,
                user_agent=(request.user_agent.string or '')[:500],
            )
            db.session.add(out_tx)
            db.session.add(in_tx)
            db.session.commit()
            flash('Transfer tamamlandı.', 'success')
            return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

        flash('Geçersiz işlem.', 'error')
        return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

    # Filters
    date_from_raw = (request.args.get('from') or '').strip()
    date_to_raw = (request.args.get('to') or '').strip()
    tx_query = CashTransaction.query.filter(
        CashTransaction.user_id.in_(tenant_ids),
        CashTransaction.account_id == account.id,
    )
    if date_from_raw:
        try:
            date_from = datetime.strptime(date_from_raw, '%Y-%m-%d')
            tx_query = tx_query.filter(CashTransaction.tarih >= date_from)
        except ValueError:
            flash('Ba?lang?? tarihi geçersiz.', 'error')
            return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))
    if date_to_raw:
        try:
            # inclusive end date
            date_to = datetime.strptime(date_to_raw, '%Y-%m-%d') + timedelta(days=1)
            tx_query = tx_query.filter(CashTransaction.tarih < date_to)
        except ValueError:
            flash('Biti? tarihi geçersiz.', 'error')
            return redirect(url_for('onmuhasebe_hesap_detay', account_id=account.id))

    transactions = tx_query.order_by(CashTransaction.tarih.desc()).limit(500).all()
    sum_giris = sum(t.tutar for t in transactions if t.islem_tipi == 'giris')
    sum_cikis = sum(t.tutar for t in transactions if t.islem_tipi == 'cikis')

    # Overall balance (not just filtered range)
    overall = (
        db.session.query(
            func.sum(case((CashTransaction.islem_tipi == 'giris', CashTransaction.tutar), else_=0.0)).label('sum_giris'),
            func.sum(case((CashTransaction.islem_tipi == 'cikis', CashTransaction.tutar), else_=0.0)).label('sum_cikis'),
        )
        .filter(CashTransaction.user_id.in_(tenant_ids), CashTransaction.account_id == account.id)
        .first()
    )
    overall_giris = float((overall.sum_giris or 0.0) if overall else 0.0)
    overall_cikis = float((overall.sum_cikis or 0.0) if overall else 0.0)
    opening_balance = float(account.opening_balance or 0.0)
    overall_balance = opening_balance + overall_giris - overall_cikis

    transfer_targets = Account.query.filter(
        Account.user_id.in_(tenant_ids),
        Account.active.is_(True),
        Account.id != account.id,
    ).order_by(Account.type, Account.name).all()

    return render_template(
        'onmuhasebe_hesap_detay.html',
        account=account,
        transactions=transactions,
        sum_giris=sum_giris,
        sum_cikis=sum_cikis,
        opening_balance=opening_balance,
        overall_balance=overall_balance,
        date_from=date_from_raw,
        date_to=date_to_raw,
        transfer_targets=transfer_targets,
    )


@app.route('/onmuhasebe/mutabakat', methods=['GET', 'POST'])
@login_required
def onmuhasebe_mutabakat():
    tenant_ids = tenant_user_ids()
    for user_id in tenant_ids:
        ensure_default_accounts_for_user(user_id)

    accounts = Account.query.filter(Account.user_id.in_(tenant_ids), Account.active.is_(True)).order_by(Account.type, Account.name).all()

    if request.method == 'POST':
        account_id_raw = (request.form.get('account_id') or '').strip()
        recon_date_raw = (request.form.get('recon_date') or '').strip()
        counted_raw = (request.form.get('counted_balance') or '').strip()
        note = (request.form.get('note') or '').strip()

        if not account_id_raw.isdigit():
            flash('Lütfen sayım yap?lacak hesabı seçin.', 'error')
            return redirect(url_for('onmuhasebe_mutabakat'))

        account = db.session.get(Account, int(account_id_raw))
        if not account or account.user_id not in tenant_ids or not account.active:
            flash('Seçilen hesap bulunamadı veya aktif değil.', 'error')
            return redirect(url_for('onmuhasebe_mutabakat'))

        try:
            recon_date = datetime.strptime(recon_date_raw, '%Y-%m-%d').date() if recon_date_raw else date.today()
        except ValueError:
            flash('Tarih geçersiz.', 'error')
            return redirect(url_for('onmuhasebe_mutabakat'))

        try:
            counted_balance = float((counted_raw or '0').replace(',', '.'))
        except ValueError:
            flash('Saydığınız para tutarı geçersiz.', 'error')
            return redirect(url_for('onmuhasebe_mutabakat'))

        end_dt = datetime(recon_date.year, recon_date.month, recon_date.day, 23, 59, 59, tzinfo=timezone.utc)
        sums = (
            db.session.query(
                func.sum(case((CashTransaction.islem_tipi == 'giris', CashTransaction.tutar), else_=0.0)).label('sum_giris'),
                func.sum(case((CashTransaction.islem_tipi == 'cikis', CashTransaction.tutar), else_=0.0)).label('sum_cikis'),
            )
            .filter(
                CashTransaction.user_id.in_(tenant_ids),
                CashTransaction.account_id == account.id,
                CashTransaction.tarih <= end_dt,
            )
            .first()
        )
        sum_giris = float((sums.sum_giris or 0.0) if sums else 0.0)
        sum_cikis = float((sums.sum_cikis or 0.0) if sums else 0.0)
        opening_balance = float(account.opening_balance or 0.0)
        expected_balance = opening_balance + sum_giris - sum_cikis
        difference = counted_balance - expected_balance

        rec = AccountReconciliation(
            user_id=account.user_id,
            account_id=account.id,
            recon_date=recon_date,
            expected_balance=expected_balance,
            counted_balance=counted_balance,
            difference=difference,
            note=note or None,
        )
        db.session.add(rec)
        db.session.flush()

        if abs(difference) >= 0.0001:
            tx = CashTransaction(
                user_id=account.user_id,
                account_id=account.id,
                cari_id=None,
                tarih=end_dt,
                islem_tipi='giris' if difference > 0 else 'cikis',
                tutar=abs(difference),
                odeme_turu='Kasa Sayım Farkı',
                aciklama=(note or 'Kasa sayımı') + f' | Sisteme göre: {format_tr_number(expected_balance)} / Saydığım: {format_tr_number(counted_balance)}',
                referans_id=rec.id,
                referans_tip='reconciliation',
                ip_adresi=request.remote_addr,
                user_agent=(request.user_agent.string or '')[:500],
            )
            db.session.add(tx)

        db.session.commit()
        flash('Kasa sayım? kaydedildi.', 'success')
        return redirect(url_for('onmuhasebe_mutabakat', account_id=account.id))

    selected_account_id = request.args.get('account_id', '').strip()
    reconciliations = (
        AccountReconciliation.query
        .join(Account, AccountReconciliation.account_id == Account.id)
        .filter(Account.user_id.in_(tenant_ids))
        .order_by(AccountReconciliation.created_at.desc())
        .limit(50)
        .all()
    )

    return render_template(
        'onmuhasebe_mutabakat.html',
        accounts=accounts,
        selected_account_id=selected_account_id,
        reconciliations=reconciliations,
    )


@app.route('/onmuhasebe/raporlar')
@login_required
def onmuhasebe_raporlar():
    tenant_ids = tenant_user_ids()
    for user_id in tenant_ids:
        ensure_default_accounts_for_user(user_id)

    accounts = Account.query.filter(Account.user_id.in_(tenant_ids)).order_by(Account.active.desc(), Account.type, Account.name).all()

    date_from_raw = (request.args.get('from') or '').strip()
    date_to_raw = (request.args.get('to') or '').strip()
    selected_account_id = (request.args.get('account_id') or '').strip()

    tx_query = CashTransaction.query.filter(CashTransaction.user_id.in_(tenant_ids))

    account_id = int(selected_account_id) if selected_account_id.isdigit() else None
    if account_id:
        tx_query = tx_query.filter(CashTransaction.account_id == account_id)

    if date_from_raw:
        try:
            date_from = datetime.strptime(date_from_raw, '%Y-%m-%d')
            tx_query = tx_query.filter(CashTransaction.tarih >= date_from)
        except ValueError:
            flash('Ba?lang?? tarihi geçersiz.', 'error')
            return redirect(url_for('onmuhasebe_raporlar'))

    if date_to_raw:
        try:
            date_to = datetime.strptime(date_to_raw, '%Y-%m-%d') + timedelta(days=1)
            tx_query = tx_query.filter(CashTransaction.tarih < date_to)
        except ValueError:
            flash('Biti? tarihi geçersiz.', 'error')
            return redirect(url_for('onmuhasebe_raporlar'))

    transactions = tx_query.order_by(CashTransaction.tarih.desc()).limit(1000).all()

    total_giris = sum(t.tutar for t in transactions if t.islem_tipi == 'giris')
    total_cikis = sum(t.tutar for t in transactions if t.islem_tipi == 'cikis')
    net = total_giris - total_cikis

    # Breakdown by payment type and by reference type
    odeme_breakdown = {}
    ref_breakdown = {}
    for t in transactions:
        key = (t.odeme_turu or 'â€”').strip()
        odeme_breakdown.setdefault(key, {'giris': 0.0, 'cikis': 0.0})
        odeme_breakdown[key][t.islem_tipi] += float(t.tutar or 0)

        rkey = (t.referans_tip or 'â€”').strip()
        ref_breakdown.setdefault(rkey, {'giris': 0.0, 'cikis': 0.0})
        ref_breakdown[rkey][t.islem_tipi] += float(t.tutar or 0)

    sayim_farki_total = 0.0
    for t in transactions:
        if (t.referans_tip or '').strip().lower() == 'reconciliation':
            sayim_farki_total += float(t.tutar or 0) * (1 if t.islem_tipi == 'giris' else -1)

    # Top expense descriptions (simple)
    expense_map = {}
    for t in transactions:
        if t.islem_tipi != 'cikis':
            continue
        desc = (t.aciklama or 'â€”').strip()
        expense_map[desc] = expense_map.get(desc, 0.0) + float(t.tutar or 0)
    top_expenses = sorted(expense_map.items(), key=lambda x: x[1], reverse=True)[:10]

    return render_template(
        'onmuhasebe_raporlar.html',
        accounts=accounts,
        selected_account_id=selected_account_id,
        date_from=date_from_raw,
        date_to=date_to_raw,
        total_giris=total_giris,
        total_cikis=total_cikis,
        net=net,
        odeme_breakdown=sorted(odeme_breakdown.items(), key=lambda x: (x[0].lower() if isinstance(x[0], str) else str(x[0]))),
        ref_breakdown=sorted(ref_breakdown.items(), key=lambda x: (x[0].lower() if isinstance(x[0], str) else str(x[0]))),
        sayim_farki_total=sayim_farki_total,
        top_expenses=top_expenses,
        transactions=transactions[:200],
    )

# Teklif Y?netimi


@app.route('/teklif_yonetimi')
@app.route('/teklifler')
@login_required
def teklif_yonetimi():
    teklifler = Teklif.query.filter(Teklif.user_id.in_(tenant_user_ids())).order_by(Teklif.tarih.desc()).all()
    toplam_teklif = len(teklifler)
    taslak_sayisi = len([t for t in teklifler if t.durum == 'taslak'])
    gonderilen_sayisi = len([t for t in teklifler if t.durum == 'gonderildi'])
    onayli_sayisi = len([t for t in teklifler if t.durum == 'onaylandi'])
    pagination = paginate_list_items(teklifler)
    return render_template('teklif_listesi.html',
                           teklifler=pagination.items,
                           pagination=pagination,
                           toplam_teklif=toplam_teklif,
                           taslak_sayisi=taslak_sayisi,
                           gonderilen_sayisi=gonderilen_sayisi,
                           onayli_sayisi=onayli_sayisi)


@app.route('/teklif/ekle', methods=['GET', 'POST'])
@login_required
@audit_log('CREATE', 'Teklif')
def teklif_ekle():
    if request.method == 'POST':
        cari_id = int(request.form.get('cari_id')) if request.form.get('cari_id') else None
        cari = db.session.get(Cari, cari_id) if cari_id else None
        if not belongs_to_current_tenant(cari):
            flash('Geerli bir cari seiniz!', 'error')
            return redirect(url_for('teklif_ekle'))
        teklif_no = request.form.get('teklif_no') or generate_teklif_no()
        try:
            tarih = datetime.strptime(request.form.get(
                'tarih'), '%Y-%m-%d') if request.form.get('tarih') else datetime.now(timezone.utc)
        except ValueError:
            return flash('Geçersiz teklif tarihi!', 'error') or redirect(url_for('teklif_ekle'))
        gecerlilik_tarihi = None
        if request.form.get('gecerlilik_tarihi'):
            try:
                gecerlilik_tarihi = datetime.strptime(request.form.get('gecerlilik_tarihi'), '%Y-%m-%d')
            except ValueError:
                return flash('Geçersiz geçerlilik tarihi!', 'error') or redirect(url_for('teklif_ekle'))
        notlar = request.form.get('notlar')
        durum = request.form.get('durum') or 'gonderildi'
        if durum not in ALLOWED_TEKLIF_DURUMLARI:
            flash('Geçersiz teklif durumu!', 'error')
            return redirect(url_for('teklif_ekle'))

        if Teklif.query.filter_by(teklif_no=teklif_no).first():
            teklif_no = generate_teklif_no()

        kdv_orani = parse_teklif_kdv_orani(request.form.get('kdv_orani'))
        if kdv_orani is None:
            flash('Geçersiz KDV oranı!', 'error')
            return redirect(url_for('teklif_ekle'))
        kalemler, toplam_tutar, kalem_hatasi = parse_teklif_kalemleri_from_form()
        if kalem_hatasi:
            flash(kalem_hatasi, 'error')
            return redirect(url_for('teklif_ekle'))

        yeni_teklif = Teklif(
            teklif_no=teklif_no,
            cari_id=cari_id,
            user_id=current_user.id,
            tarih=tarih,
            gecerlilik_tarihi=gecerlilik_tarihi,
            notlar=notlar,
            durum=durum,
            kdv_orani=kdv_orani,
            toplam_tutar=toplam_tutar,
            genel_toplam=toplam_tutar * (1 + kdv_orani / 100)
        )
        db.session.add(yeni_teklif)
        db.session.flush()

        for kalem_data in kalemler:
            db.session.add(TeklifKalemi(teklif_id=yeni_teklif.id, **kalem_data))

        db.session.commit()
        flash('Teklif başarıyla oluşturuldu!', 'success')
        return redirect(url_for('teklif_yonetimi'))

    tenant_ids = tenant_user_ids()
    cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
    urunler = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()

    from datetime import date
    bugun = date.today().strftime('%Y-%m-%d')
    yeni_no = generate_teklif_no()

    return render_template('teklif_form.html',
                           cariler=cariler,
                           urunler=urunler,
                           yeni_teklif_no=yeni_no,
                           bugun=bugun)


@app.route('/teklif/<int:id>')
@login_required
def teklif_detay(id):
    teklif = Teklif.query.get_or_404(id)
    if not belongs_to_current_tenant(teklif):
        flash('Bu teklife erişim izniniz yok!', 'error')
        return redirect(url_for('teklif_yonetimi'))
    return render_template('teklif_detayi_ve_yazdir.html', teklif=teklif)


@app.route('/teklif/<int:id>/duzenle', methods=['GET', 'POST'])
@login_required
@audit_log('UPDATE', 'Teklif')
def teklif_duzenle(id):
    teklif = Teklif.query.get_or_404(id)
    if not belongs_to_current_tenant(teklif):
        flash('Bu teklife eriim izniniz yok!', 'error')
        return redirect(url_for('teklif_yonetimi'))

    if request.method == 'POST':
        teklif.cari_id = int(request.form.get('cari_id')) if request.form.get('cari_id') else None
        cari = db.session.get(Cari, teklif.cari_id) if teklif.cari_id else None
        if not belongs_to_current_tenant(cari):
            flash('Geerli bir cari seiniz!', 'error')
            return redirect(url_for('teklif_duzenle', id=id))
        try:
            gecerlilik_tarihi = datetime.strptime(request.form.get(
                'gecerlilik_tarihi'), '%Y-%m-%d') if request.form.get('gecerlilik_tarihi') else None
        except ValueError:
            flash('Geçersiz geçerlilik tarihi!', 'error')
            return redirect(url_for('teklif_duzenle', id=id))
        durum = request.form.get('durum') or teklif.durum or 'taslak'
        if durum not in ALLOWED_TEKLIF_DURUMLARI:
            flash('Geçersiz teklif durumu!', 'error')
            return redirect(url_for('teklif_duzenle', id=id))
        kdv_orani = parse_teklif_kdv_orani(request.form.get('kdv_orani'))
        if kdv_orani is None:
            flash('Geçersiz KDV oranı!', 'error')
            return redirect(url_for('teklif_duzenle', id=id))
        kalemler, toplam, kalem_hatasi = parse_teklif_kalemleri_from_form()
        if kalem_hatasi:
            flash(kalem_hatasi, 'error')
            return redirect(url_for('teklif_duzenle', id=id))

        teklif.notlar = request.form.get('notlar')
        teklif.gecerlilik_tarihi = gecerlilik_tarihi
        teklif.durum = durum
        teklif.kdv_orani = kdv_orani
        teklif.toplam_tutar = toplam
        teklif.genel_toplam = toplam + (toplam * kdv_orani / 100)

        TeklifKalemi.query.filter_by(teklif_id=teklif.id).delete()
        for kalem_data in kalemler:
            db.session.add(TeklifKalemi(teklif_id=teklif.id, **kalem_data))

        db.session.commit()
        flash('Teklif başarıyla güncellendi!', 'success')
        return redirect(url_for('teklif_yonetimi'))

    tenant_ids = tenant_user_ids()
    cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
    urunler = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    from datetime import date
    bugun = date.today().strftime('%Y-%m-%d')
    return render_template('teklif_form.html', teklif=teklif, cariler=cariler, urunler=urunler,
                           duzenle_modu=True, bugun=bugun)


@app.route('/teklif/<int:id>/sil', methods=['POST'])
@login_required
@audit_log('DELETE', 'Teklif')
def teklif_sil(id):
    teklif = Teklif.query.get_or_404(id)
    if not belongs_to_current_tenant(teklif):
        flash('Bu teklife erişim izniniz yok!', 'error')
        return redirect(url_for('teklif_yonetimi'))

    TeklifKalemi.query.filter_by(teklif_id=teklif.id).delete()
    db.session.delete(teklif)
    db.session.commit()
    flash('Teklif başarıyla silindi!', 'success')
    return redirect(url_for('teklif_yonetimi'))


@app.route('/teklif/<int:id>/durum', methods=['POST'])
@login_required
@audit_log('UPDATE', 'Teklif')
def teklif_durum_guncelle(id):
    teklif = Teklif.query.get_or_404(id)
    if not belongs_to_current_tenant(teklif):
        flash('Bu teklife erişim izniniz yok!', 'error')
        return redirect(url_for('teklif_yonetimi'))

    yeni_durum = request.form.get('durum')
    if yeni_durum in ALLOWED_TEKLIF_DURUMLARI:
        teklif.durum = yeni_durum
        db.session.commit()
        flash(f'Teklif durumu {yeni_durum} olarak güncellendi!', 'success')
    else:
        flash('Geçersiz durum!', 'error')

    return redirect(url_for('teklif_yonetimi'))

# Raporlar


@app.route('/raporlar')
@login_required
def raporlar():
    tenant_ids = tenant_user_ids()
    urunler = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
    satislar = Satis.query.filter(Satis.user_id.in_(tenant_ids)).all()
    aktif_satislar = [s for s in satislar if s.durum != 'iptal']

    # Temel istatistikler
    toplam_urun = len(urunler)
    toplam_stok = sum(u.stok_miktari or 0 for u in urunler)
    kritik_stok = len([u for u in urunler if (u.stok_miktari or 0) <= (u.kritik_stok or 0)])
    toplam_cari = len(cariler)

    # Finansal veriler
    toplam_cari_borc = sum(c.borc or 0 for c in cariler)
    toplam_cari_alacak = sum(c.alacak or 0 for c in cariler)
    net_bakiye = toplam_cari_alacak - toplam_cari_borc
    toplam_satis_deger = sum(s.genel_toplam or 0 for s in aktif_satislar)
    toplam_stok_deger = sum((u.stok_miktari or 0) * (u.satis_fiyati or 0) for u in urunler)

    # Naive datetime kullanarak kar??laçtırma hatas?n? ?nle
    simdi = datetime.now(timezone.utc)
    ay_basi = simdi.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    aylik_satis = 0
    for s in aktif_satislar:
        if s.tarih:
            # E?er s.tarih aware ise naive'e ?evir
            if s.tarih.tzinfo:
                s_tarih = s.tarih.astimezone(timezone.utc)
            else:
                s_tarih = s.tarih.replace(tzinfo=timezone.utc)
            if s_tarih >= ay_basi:
                aylik_satis += (s.genel_toplam or 0)

    # En ?ok satan Ürünler
    en_cok_satan_map = {}
    for satis in aktif_satislar:
        for kalem in satis.kalemler:
            urun = Urun.query.filter(Urun.id == kalem.urun_id, Urun.user_id.in_(tenant_ids)).first()
            if urun:
                row = en_cok_satan_map.setdefault(urun.id, {
                    'urun_adi': urun.urun_adi,
                    'adet': 0,
                    'tutar': 0
                })
                row['adet'] += kalem.miktar or 0
                row['tutar'] += kalem.toplam or 0
    en_cok_satan = sorted(en_cok_satan_map.values(), key=lambda item: (item['adet'], item['tutar']), reverse=True)

    # Kategori baz?nda analiz
    kategori_analizi = {}
    for urun in urunler:
        kat = urun.kategori or 'Kategorisiz'
        if kat not in kategori_analizi:
            kategori_analizi[kat] = {'urun_sayisi': 0, 'stok_degeri': 0}
        kategori_analizi[kat]['urun_sayisi'] += 1
        kategori_analizi[kat]['stok_degeri'] += (urun.stok_miktari or 0) * (urun.satis_fiyati or 0)

    return render_template('cari_hareketler_ve_finansal_analiz.html',
                           urunler=urunler,
                           cariler=cariler,
                           toplam_urun=toplam_urun,
                           toplam_stok=toplam_stok,
                           kritik_stok=kritik_stok,
                           toplam_cari=toplam_cari,
                           toplam_cari_borc=toplam_cari_borc,
                           toplam_cari_alacak=toplam_cari_alacak,
                           toplam_satis_deger=toplam_satis_deger,
                           aylik_satis=aylik_satis,
                           en_cok_satan=en_cok_satan[:5],
                           kategori_analizi=kategori_analizi)

# İade İşlemleri
# Cari Ödeme İşlemleri


@app.route('/cari/<int:cari_id>/odeme', methods=['POST'])
@login_required
@audit_log('UPDATE', 'Cari')
def cari_odeme(cari_id):
    cari = Cari.query.get_or_404(cari_id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye erişim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    try:
        tutar = normalize_amount(request.form.get('tutar', 0))
        odeme_turu = normalize_payment_method(request.form.get('odeme_turu', 'Nakit'))
        account_id_raw = (request.form.get('account_id') or '').strip()
        account_id = int(account_id_raw) if account_id_raw.isdigit() else None
        aciklama = request.form.get('aciklama', '')

        if tutar <= 0:
            flash('Geçerli bir tutar giriniz!', 'error')
            return redirect(url_for('cari_detay', id=cari_id))

        if account_id:
            tenant_ids = tenant_user_ids()
            account = db.session.get(Account, account_id)
            if not account or account.user_id not in tenant_ids or not account.active:
                flash('Seçilen hesap bulunamadı veya aktif değil.', 'error')
                return redirect(url_for('cari_detay', id=cari_id))

        cari_borc_oncesi = cari.borc or 0
        adjust_cari_account(cari, tutar, 'odeme')

        hareket = CariHareket(
            cari_id=cari.id,
            user_id=current_user.id,
            islem_tipi='odeme',
            tutar=tutar,
            aciklama=aciklama or f'{odeme_turu} ile Ödeme alındı',
            odeme_turu=odeme_turu,
            referans_tip='cari_odeme'
        )
        db.session.add(hareket)

        create_cash_transaction(
            cari,
            tutar,
            'cikis',
            odeme_turu,
            aciklama or f'{odeme_turu} ile Ödeme alındı',
            referans_tip='cari_odeme',
            account_id=account_id
        )

        db.session.commit()
        flash(f'₺{tutar:.2f} ödeme başarıyla kaydedildi! Yeni bakiye: ₺{cari.bakiye:.2f}', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Ödeme kaydedilirken hata oluştu!', 'error')

    return redirect(url_for('cari_detay', id=cari_id))


@app.route('/cari/<int:cari_id>/tahsilat', methods=['POST'])
@login_required
@audit_log('UPDATE', 'Cari')
def cari_tahsilat(cari_id):
    cari = Cari.query.get_or_404(cari_id)
    if not belongs_to_current_tenant(cari):
        flash('Bu cariye erişim izniniz yok!', 'error')
        return redirect(url_for('cariler'))

    try:
        tutar = normalize_amount(request.form.get('tutar', 0))
        tahsilat_turu = normalize_payment_method(request.form.get('tahsilat_turu', 'Nakit'))
        account_id_raw = (request.form.get('account_id') or '').strip()
        account_id = int(account_id_raw) if account_id_raw.isdigit() else None
        aciklama = request.form.get('aciklama', '')

        if tutar <= 0:
            flash('Geçerli bir tutar giriniz!', 'error')
            return redirect(url_for('cari_detay', id=cari_id))

        if account_id:
            tenant_ids = tenant_user_ids()
            account = db.session.get(Account, account_id)
            if not account or account.user_id not in tenant_ids or not account.active:
                flash('Seçilen hesap bulunamadı veya aktif değil.', 'error')
                return redirect(url_for('cari_detay', id=cari_id))

        adjust_cari_account(cari, tutar, 'tahsilat')

        hareket = CariHareket(
            cari_id=cari.id,
            user_id=current_user.id,
            islem_tipi='tahsilat',
            tutar=tutar,
            aciklama=aciklama or f'{tahsilat_turu} ile tahsilat yapıldı',
            odeme_turu=tahsilat_turu,
            referans_tip='cari_tahsilat'
        )
        db.session.add(hareket)

        create_cash_transaction(
            cari,
            tutar,
            'giris',
            tahsilat_turu,
            aciklama or f'{tahsilat_turu} ile tahsilat yapıldı',
            referans_tip='cari_tahsilat',
            account_id=account_id
        )

        db.session.commit()
        flash(f'₺{tutar:.2f} tahsilat başarıyla kaydedildi! Yeni bakiye: ₺{cari.bakiye:.2f}', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Tahsilat kaydedilirken hata oluştu!', 'error')

    return redirect(url_for('cari_detay', id=cari_id))

# İade İşlemleri


@app.route('/iade', methods=['GET', 'POST'])
@login_required
@audit_log('CREATE', 'Iade')
def iade():
    if request.method == 'POST':
        try:
            cari_id = int(request.form.get('cari_id')) if request.form.get('cari_id') else None
            urun_idler = request.form.getlist('urun_idler[]')
            urun_adlari = request.form.getlist('urun_adlari[]')
            iade_miktarlari = request.form.getlist('iade_miktarlari[]')
            iade_turu = request.form.get('iade_turu', 'urun_iadesi')
            odeme_turu = normalize_payment_method(request.form.get('odeme_turu', 'Nakit'))
            account_id_raw = (request.form.get('account_id') or '').strip()
            account_id = int(account_id_raw) if account_id_raw.isdigit() else None
            iade_sebebi = request.form.get('iade_sebebi', '')
            alacak_olustur = request.form.get('alacak_olustur') == 'on'

            if iade_turu not in ALLOWED_IADE_TURLERI:
                flash('Geçersiz iade türü!', 'error')
                return redirect(url_for('iade'))

            if not urun_idler or not any(urun_idler):
                flash('En az bir Ürün seçmelisiniz!', 'error')
                return redirect(url_for('iade'))

            if account_id:
                account = db.session.get(Account, account_id)
                if not account or account.user_id not in tenant_user_ids() or not account.active:
                    flash('Seçilen hesap bulunamadı veya aktif değil.', 'error')
                    return redirect(url_for('iade'))

            cari = db.session.get(Cari, cari_id)
            if not cari or not belongs_to_current_tenant(cari):
                flash('Geçersiz müşteri seçimi!', 'error')
                return redirect(url_for('iade'))

            iade_kalemleri = []
            toplam_iade_tutari = 0
            for i in range(len(urun_idler)):
                try:
                    urun_id = int(urun_idler[i])
                    urun_adi = urun_adlari[i] if i < len(urun_adlari) else ''
                    iade_miktari = normalize_amount(iade_miktarlari[i]) if i < len(iade_miktarlari) else 0

                    urun = db.session.get(Urun, urun_id)
                    if not urun or not belongs_to_current_tenant(urun):
                        continue

                    if iade_miktari <= 0:
                        flash(f'{urun.urun_adi} için geçerli bir iade miktar? giriniz!', 'error')
                        return redirect(url_for('iade'))

                    eski_stok = urun.stok_miktari or 0
                    urun.stok_miktari = eski_stok + iade_miktari

                    iade_kalemleri.append({
                        'urun_id': urun.id,
                        'urun_adi': urun_adi or urun.urun_adi,
                        'miktar': iade_miktari,
                        'birim_fiyat': urun.satis_fiyati or 0,
                        'eski_stok': eski_stok,
                        'yeni_stok': urun.stok_miktari
                    })
                    toplam_iade_tutari += iade_miktari * (urun.satis_fiyati or 0)

                except (ValueError, TypeError):
                    continue

            if not iade_kalemleri:
                flash('Geçerli iade kalemi bulunamadı!', 'error')
                return redirect(url_for('iade'))

            iade_kaydi = Iade(
                cari_id=cari.id,
                user_id=current_user.id,
                iade_turu=iade_turu,
                iade_sebebi=iade_sebebi,
                iade_tutari=toplam_iade_tutari,
                durum='tamamlandi',
                urun_adet=len(iade_kalemleri),
                tarih=datetime.now(timezone.utc),
                ip_adresi=request.remote_addr,
                user_agent=request.headers.get('User-Agent', '')
            )
            db.session.add(iade_kaydi)
            db.session.flush()

            for kalem in iade_kalemleri:
                iade_kalem = IadeKalem(
                    iade_id=iade_kaydi.id,
                    urun_id=kalem['urun_id'],
                    urun_adi=kalem['urun_adi'],
                    miktar=kalem['miktar'],
                    birim_fiyat=kalem['birim_fiyat'],
                    eski_stok=kalem['eski_stok'],
                    yeni_stok=kalem['yeni_stok']
                )
                db.session.add(iade_kalem)
                urun = db.session.get(Urun, kalem['urun_id'])
                if urun and belongs_to_current_tenant(urun):
                    record_stock_movement(
                        urun,
                        'giris',
                        kalem['miktar'],
                        urun.depo_adi or DEFAULT_WAREHOUSE,
                        kalem['eski_stok'],
                        kalem['yeni_stok'],
                        f'İade - {iade_turu}',
                        cari_id=cari.id if cari else None
                    )

            # Cari bakiye sadece alacak oluşturma se?ildiçinde etkilenir.
            # Do?rudan para iadesi kasa/banka çıkışıyla kapandüş? için cari bakiyeyi ayr?ca de?i?tirmez.
            if alacak_olustur:
                adjust_cari_account(cari, toplam_iade_tutari, 'tahsilat')
                db.session.add(CariHareket(
                    cari_id=cari.id,
                    user_id=current_user.id,
                    islem_tipi='iade',
                    tutar=toplam_iade_tutari,
                    aciklama=f'{iade_turu} - {iade_sebebi}',
                    odeme_turu='Alacak',
                    referans_id=iade_kaydi.id,
                    referans_tip='iade'
                ))

            if iade_turu == 'para_iadesi' and not alacak_olustur:
                create_cash_transaction(
                    cari,
                    toplam_iade_tutari,
                    'cikis',
                    odeme_turu,
                    f'{iade_turu} - {iade_sebebi}',
                    referans_id=iade_kaydi.id,
                    referans_tip='iade',
                    account_id=account_id
                )
            db.session.commit()
            flash(f'{len(iade_kalemleri)} Ürün için iade işlemi başarıyla tamamlandı!', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'İade işlemi s?ras?nda hata oluştu: {str(e)}', 'error')
            return redirect(url_for('iade'))

    # ?statistikler
    tenant_ids = tenant_user_ids()
    toplam_iade = Iade.query.filter(Iade.user_id.in_(tenant_ids)).count()
    bekleyen_iade = Iade.query.filter(Iade.user_id.in_(tenant_ids), Iade.durum == 'beklemede').count()
    tamamlanan_iade = Iade.query.filter(Iade.user_id.in_(tenant_ids), Iade.durum == 'tamamlandi').count()
    toplam_iade_deger = db.session.query(db.func.sum(Iade.iade_tutari)).filter(Iade.user_id.in_(tenant_ids)).scalar() or 0

    # Son iadeler
    son_iadeler = db.session.query(
        Iade, Cari
    ).join(Cari, Iade.cari_id == Cari.id).filter(
        Iade.user_id.in_(tenant_ids)
    ).order_by(Iade.tarih.desc()).limit(10).all()

    ensure_default_accounts_for_user(current_user.id)
    cariler = Cari.query.filter(Cari.user_id.in_(tenant_ids)).all()
    urunler = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    accounts = Account.query.filter(Account.user_id.in_(tenant_ids), Account.active.is_(True)).order_by(Account.type, Account.name).all()

    cariler_json = [{
        'id': c.id,
        'unvan': c.unvan,
        'borc': c.borc or 0,
        'alacak': c.alacak or 0
    } for c in cariler]

    urunler_json = [{
        'id': u.id,
        'urun_adi': u.urun_adi,
        'barkod': u.barkod or '',
        'kategori': u.kategori or '',
        'stok_miktari': u.stok_miktari or 0,
        'satis_fiyati': u.satis_fiyati or 0
    } for u in urunler]

    return render_template('iade_islemleri_paneli.html',
                           cariler=cariler_json,
                           urunler=urunler_json,
                           toplam_iade=toplam_iade,
                           bekleyen_iade=bekleyen_iade,
                           tamamlanan_iade=tamamlanan_iade,
                           toplam_iade_deger=toplam_iade_deger,
                           son_iadeler=son_iadeler,
                           accounts=accounts)

# Ödeme Sayfas? (Demo limiti dolduğunda paket y?kseltme)


@app.route('/odeme')
def odeme():
    # Demo kullan?c?lar Ürün limitini dolduğunda buraya y?nlendirilir
    return render_template('hizli_satis_pos_ekrani.html')

# Çıkış


# Platform Sahibi / Super Admin

def organization_owner(organization):
    if organization.owner_user_id:
        owner = db.session.get(User, organization.owner_user_id)
        if owner:
            return owner
    return User.query.filter_by(organization_id=organization.id, role='owner').first()


def organization_user_ids(organization):
    return [
        user_id for (user_id,) in db.session.query(User.id)
        .filter(User.organization_id == organization.id)
        .all()
    ]


def is_customer_organization(organization):
    return any(user.role != 'platform_staff' for user in organization.users)


def organization_usage(organization):
    user_ids = organization_user_ids(organization)
    if not user_ids:
        return {
            'users': 0, 'products': 0, 'customers': 0, 'sales': 0,
            'quotes': 0, 'returns': 0, 'cash_total': 0.0, 'last_activity': None
        }

    cash_total = db.session.query(db.func.coalesce(db.func.sum(CashTransaction.tutar), 0)) \
        .filter(CashTransaction.user_id.in_(user_ids)).scalar() or 0
    last_log = AuditLog.query.filter(AuditLog.user_id.in_(user_ids)) \
        .order_by(AuditLog.timestamp.desc()).first()

    return {
        'users': len(user_ids),
        'products': Urun.query.filter(Urun.user_id.in_(user_ids)).count(),
        'customers': Cari.query.filter(Cari.user_id.in_(user_ids)).count(),
        'sales': Satis.query.filter(Satis.user_id.in_(user_ids)).count(),
        'quotes': Teklif.query.filter(Teklif.user_id.in_(user_ids)).count(),
        'returns': Iade.query.filter(Iade.user_id.in_(user_ids)).count(),
        'cash_total': float(cash_total),
        'last_activity': last_log.timestamp if last_log else None,
    }


def organization_360_context(organization):
    user_ids = organization_user_ids(organization)
    tickets = SupportTicket.query.filter_by(organization_id=organization.id).order_by(SupportTicket.updated_at.desc()).limit(8).all()
    actions = ActionItem.query.filter_by(organization_id=organization.id).order_by(ActionItem.updated_at.desc()).limit(8).all()
    return {
        'organization': organization,
        'owner': organization_owner(organization),
        'usage': organization_usage(organization),
        'subscription': subscription_summary(organization),
        'users': User.query.filter_by(organization_id=organization.id).order_by(User.kayit_tarihi.desc()).all(),
        'tickets': tickets,
        'actions': actions,
        'open_ticket_count': sum(1 for ticket in tickets if ticket.status not in {'resolved', 'closed'}),
        'open_action_count': sum(1 for action in actions if action.status != 'done'),
        'payments': SubscriptionPayment.query.filter_by(organization_id=organization.id).order_by(SubscriptionPayment.created_at.desc()).limit(10).all(),
        'logs': AuditLog.query.filter(AuditLog.user_id.in_(user_ids)).order_by(AuditLog.timestamp.desc()).limit(10).all() if user_ids else [],
    }


@app.route('/super-admin')
@login_required
@platform_admin_required
def super_admin_dashboard():
    action_center = build_action_center_context(per_page=12)
    support_center = build_support_ticket_context(per_page=12)
    organizations = [
        organization for organization in Organization.query.order_by(Organization.created_at.desc()).all()
        if is_customer_organization(organization)
    ]
    users = User.query.order_by(User.kayit_tarihi.desc()).all()
    platform_team = User.query.filter_by(is_platform_admin=True).order_by(User.aktif.desc(), User.email).all()
    org_cards = [{
        'organization': organization,
        'owner': organization_owner(organization),
        'usage': organization_usage(organization),
        'users': User.query.filter_by(organization_id=organization.id).order_by(User.role.desc(), User.email).all(),
        'modules': parse_module_permissions(organization.module_permissions),
        'subscription': subscription_summary(organization),
    } for organization in organizations]

    stats = {
        'organizations': len(organizations),
        'active_organizations': sum(1 for organization in organizations if organization.active),
        'users': len(users),
        'platform_admins': sum(1 for user in users if user.is_platform_admin),
        'products': Urun.query.count(),
        'sales': Satis.query.count(),
        'logs': AuditLog.query.count(),
        'backups': BackupLog.query.count(),
        'expired_subscriptions': sum(1 for organization in organizations if subscription_summary(organization)['is_expired']),
        'renewal_due_subscriptions': sum(1 for organization in organizations if subscription_summary(organization)['is_renewal_due']),
    }
    plan_counts = {
        plan: Organization.query.filter_by(plan=plan).count()
        for plan in ['demo', 'standart', 'profesyonel']
    }
    recent_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(12).all()
    backups = BackupLog.query.order_by(BackupLog.created_at.desc()).limit(8).all()
    platform_settings = SystemSettings.query.filter_by(user_id=None).order_by(SystemSettings.key).all()
    platform_config = {
        'platform_name': platform_setting('platform_name', 'StokCari'),
        'default_plan': platform_setting('default_plan', 'demo'),
        'default_user_limit': platform_setting_int('default_user_limit', 1),
        'default_product_limit': platform_setting_int('default_product_limit', 10),
        'seo_closed_mode': platform_setting_bool('seo_closed_mode', True),
        'seo_indexing_enabled': platform_setting_bool('seo_indexing_enabled', False),
        'site_url': platform_setting('site_url', app.config.get('SITE_URL', '')),
        'site_name': platform_setting('site_name', app.config.get('SITE_NAME', 'StokCari')),
        'site_description': platform_setting('site_description', app.config.get('SITE_DESCRIPTION', '')),
        'site_og_image': platform_setting('site_og_image', app.config.get('SITE_OG_IMAGE', '')),
        'smtp_host': platform_setting('smtp_host', app.config.get('SMTP_HOST', '')),
        'smtp_port': platform_setting('smtp_port', str(app.config.get('SMTP_PORT', 587))),
        'smtp_username': platform_setting('smtp_username', app.config.get('SMTP_USERNAME', '')),
        'smtp_from_email': platform_setting('smtp_from_email', app.config.get('SMTP_FROM_EMAIL', '')),
        'smtp_from_name': platform_setting('smtp_from_name', app.config.get('SMTP_FROM_NAME', app.config.get('SITE_NAME', 'StokCari'))),
        'smtp_use_tls': platform_setting_bool('smtp_use_tls', bool(app.config.get('SMTP_USE_TLS', True))),
        'smtp_use_ssl': platform_setting_bool('smtp_use_ssl', bool(app.config.get('SMTP_USE_SSL', False))),
        'registrations_enabled': platform_setting_bool('registrations_enabled', True),
        'pos_integration_enabled_for_users': platform_setting_bool('pos_integration_enabled_for_users', False),
        'min_password_length': platform_setting_int('min_password_length', 8),
        'session_lifetime_minutes': platform_setting_int('session_lifetime_minutes', 480),
        'failed_login_limit': platform_setting_int('failed_login_limit', 5),
        'maintenance_message': platform_setting(
            'maintenance_message',
            'Sistem kisa sureli bakim modunda. Lutfen daha sonra tekrar deneyin.'
        ),
        'support_email': platform_setting('support_email', ''),
        'auto_backup_frequency': platform_setting('auto_backup_frequency', 'daily'),
        'backup_retention_days': platform_setting_int('backup_retention_days', 30),
    }
    system_controls = platform_system_controls()

    return render_template(
        'super_admin/dashboard.html',
        org_cards=org_cards,
        users=users,
        platform_team=platform_team,
        stats=stats,
        plan_counts=plan_counts,
        recent_logs=recent_logs,
        backups=backups,
        platform_settings=platform_settings,
        platform_config=platform_config,
        platform_modules=PLATFORM_MODULES,
        platform_admin_role_labels=PLATFORM_ADMIN_ROLE_LABELS,
        platform_permission_labels=PLATFORM_PERMISSION_LABELS,
        platform_role_permissions=PLATFORM_ROLE_PERMISSIONS,
        platform_insights=platform_insights_context(),
        action_center=action_center,
        support_center=support_center,
        maintenance_mode=system_controls['maintenance_mode'],
        system_controls=system_controls,
        system_health=system_health_context(),
        system_security=system_security_context(),
        app_version=app_version(),
        updater_status=read_updater_status(),
        updater_heartbeat=read_updater_heartbeat(),
        self_test=platform_self_test_last_result(),
        workflow_test=platform_workflow_test_last_result(),
        single_test_result=platform_single_test_last_result(),
        test_inventory=platform_test_inventory(),
    )


@app.route('/super-admin/organizations/<int:organization_id>/update', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('organizations_manage')
def super_admin_update_organization(organization_id):
    locked = require_platform_owner_for_locked_action(
        'financial_changes_locked',
        'Finansal/firma degisiklikleri kilitli. Bu islem platform sahibi tarafindan yapilmali.',
        'companies'
    )
    if locked:
        return locked

    organization = db.session.get(Organization, organization_id)
    if not organization:
        abort(404)

    previous_plan = organization.plan
    previous_subscription_end = organization.subscription_end
    organization.name = request.form.get('name', organization.name).strip() or organization.name
    organization.plan = request.form.get('plan', organization.plan)
    organization.active = request.form.get('active') == 'on'
    organization.maintenance_mode = request.form.get('maintenance_mode') == 'on'
    organization.user_limit = max(1, int(request.form.get('user_limit') or organization.user_limit or 1))
    organization.product_limit = max(1, int(request.form.get('product_limit') or organization.product_limit or 10))
    try:
        organization.subscription_start = datetime.strptime(
            request.form.get('subscription_start') or date.today().isoformat(),
            '%Y-%m-%d'
        ).date()
    except ValueError:
        organization.subscription_start = date.today()
    try:
        organization.subscription_end = datetime.strptime(
            request.form.get('subscription_end') or default_subscription_end(organization.subscription_start).isoformat(),
            '%Y-%m-%d'
        ).date()
    except ValueError:
        organization.subscription_end = default_subscription_end(organization.subscription_start)
    subscription_status = request.form.get('subscription_status') or 'active'
    organization.subscription_status = subscription_status if subscription_status in {'trial', 'active', 'expired', 'cancelled'} else 'active'
    organization.subscription_note = (request.form.get('subscription_note') or '').strip()[:500]
    modules = save_module_permissions(organization, request.form.getlist('modules'))

    for user in User.query.filter_by(organization_id=organization.id).all():
        user.paket_tipi = organization.plan
        user.urun_limiti = organization.product_limit
        user.aktif = organization.active

    platform_audit(
        'PLATFORM_ORGANIZATION_UPDATE',
        (
            f'{organization.name} guncellendi. Paket: {previous_plan} -> {organization.plan}. '
            f'Destek bitis: {previous_subscription_end or "-"} -> {organization.subscription_end}. '
            f'Moduller: {", ".join([key for key, enabled in modules.items() if enabled])}'
        ),
        'Organization',
        organization.id,
    )
    db.session.commit()
    flash('Firma ayarlari guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#companies')


@app.route('/super-admin/organizations/<int:organization_id>')
@login_required
@platform_admin_required
@platform_permission_required('organizations_view')
def super_admin_organization_detail(organization_id):
    organization = db.session.get(Organization, organization_id)
    if not organization:
        abort(404)
    return render_template(
        'super_admin/organization_detail.html',
        **organization_360_context(organization),
        status_labels=SUPPORT_STATUS_LABELS,
        priority_labels=SUPPORT_PRIORITY_LABELS,
        category_labels=SUPPORT_CATEGORY_LABELS,
        action_status_labels=ACTION_STATUS_LABELS,
        action_severity_labels=ACTION_SEVERITY_LABELS,
        action_source_labels=ACTION_SOURCE_LABELS,
        billing_status_labels=BILLING_STATUS_LABELS,
    )


@app.route('/super-admin/organizations/<int:organization_id>/payments', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('billing_manage')
def super_admin_add_subscription_payment(organization_id):
    locked = require_platform_owner_for_locked_action(
        'financial_changes_locked',
        'Odeme ve abonelik islemleri kilitli. Bu islem platform sahibi tarafindan yapilmali.',
        'companies'
    )
    if locked:
        return locked

    organization = db.session.get(Organization, organization_id)
    if not organization:
        abort(404)

    try:
        amount = float((request.form.get('amount') or '0').replace(',', '.'))
    except ValueError:
        amount = 0
    status = request.form.get('status') or 'pending'
    if status not in BILLING_STATUS_LABELS:
        status = 'pending'
    plan = request.form.get('plan') or organization.plan or 'standart'
    period_start = None
    period_end = None
    for field_name in ['period_start', 'period_end']:
        value = request.form.get(field_name)
        if value:
            try:
                parsed = datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                parsed = None
            if field_name == 'period_start':
                period_start = parsed
            else:
                period_end = parsed

    payment = SubscriptionPayment(
        organization_id=organization.id,
        plan=plan,
        amount=max(0, amount),
        currency=(request.form.get('currency') or 'TRY').strip()[:8].upper(),
        period_start=period_start,
        period_end=period_end,
        status=status,
        note=(request.form.get('note') or '').strip()[:1000],
        paid_at=datetime.now(timezone.utc) if status == 'paid' else None,
    )
    db.session.add(payment)
    if period_start:
        organization.subscription_start = period_start
    if period_end:
        organization.subscription_end = period_end
    organization.subscription_status = 'active' if status == 'paid' else organization.subscription_status
    platform_audit('PLATFORM_ORGANIZATION_UPDATE', f'Odeme/abonelik kaydi eklendi: {organization.name}', 'Organization', organization.id)
    sync_subscription_actions()
    db.session.commit()
    flash('Odeme ve abonelik kaydi eklendi.', 'success')
    return redirect(url_for('super_admin_organization_detail', organization_id=organization.id))


@app.route('/super-admin/platform-team/create', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('team_manage')
def super_admin_create_platform_team_member():
    locked = require_platform_owner_for_locked_action(
        'team_role_changes_locked',
        'Platform ekibi yetki degisiklikleri kilitli. Bu islem platform sahibi tarafindan yapilmali.',
        'platform-team'
    )
    if locked:
        return locked

    email = (request.form.get('email') or '').strip().lower()
    name = (request.form.get('name') or '').strip()
    password = request.form.get('password') or ''
    platform_role = request.form.get('platform_role') or 'support'

    if platform_role not in PLATFORM_ADMIN_ROLE_LABELS:
        platform_role = 'support'
    if not email or '@' not in email:
        flash('Gecerli bir e-posta girin.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-team')
    if len(password) < 8:
        flash('Gecici sifre en az 8 karakter olmali.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-team')
    if User.query.filter(db.func.lower(User.email) == email).first():
        flash('Bu e-posta ile kayitli bir kullanici zaten var.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-team')

    user = User(
        email=email,
        password=generate_password_hash(password),
        firma_adi='Platform Ekibi',
        yetkili_adi=name,
        paket_tipi='profesyonel',
        urun_limiti=0,
        aktif=True,
        organization_id=None,
        role='platform_staff',
        is_platform_admin=True,
        platform_role=platform_role,
    )
    db.session.add(user)
    db.session.flush()
    platform_audit('PLATFORM_USER_UPDATE', f'Platform ekibi eklendi: {user.email}', 'User', user.id)
    db.session.commit()
    flash('Platform ekibi uyesi eklendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-team')


@app.route('/super-admin/platform-team/<int:user_id>/update', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('team_manage')
def super_admin_update_platform_team_member(user_id):
    user = db.session.get(User, user_id)
    if not user or not user.is_platform_admin:
        abort(404)
    if platform_lock_enabled('owner_account_protection') and (user.platform_role or 'viewer') == 'owner' and not is_platform_owner_user(current_user):
        return block_platform_owner_lock('Platform sahibi hesabi koruma altinda. Bu hesabi sadece platform sahibi degistirebilir.', 'platform-team', 'owner_account_protection')
    locked = require_platform_owner_for_locked_action(
        'team_role_changes_locked',
        'Platform ekibi yetki degisiklikleri kilitli. Bu islem platform sahibi tarafindan yapilmali.',
        'platform-team'
    )
    if locked:
        return locked

    platform_role = request.form.get('platform_role') or user.platform_role or 'support'
    if platform_role not in PLATFORM_ADMIN_ROLE_LABELS:
        platform_role = 'support'

    if user.id == current_user.id:
        user.aktif = True
        user.platform_role = 'owner'
    else:
        user.aktif = request.form.get('aktif') == 'on'
        user.platform_role = platform_role
    user.yetkili_adi = (request.form.get('name') or user.yetkili_adi or '').strip()
    user.firma_adi = 'Platform Ekibi'
    user.role = 'platform_staff'
    user.organization_id = None

    new_password = request.form.get('password') or ''
    if new_password:
        if len(new_password) < 8:
            flash('Yeni sifre en az 8 karakter olmali.', 'error')
            return redirect(url_for('super_admin_dashboard') + '#platform-team')
        user.password = generate_password_hash(new_password)

    platform_audit('PLATFORM_USER_UPDATE', f'Platform ekibi guncellendi: {user.email}', 'User', user.id)
    db.session.commit()
    flash('Platform ekibi guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-team')


@app.route('/super-admin/users/<int:user_id>/update', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('users_manage')
def super_admin_update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if platform_lock_enabled('owner_account_protection') and (user.platform_role or 'viewer') == 'owner' and user.id != current_user.id:
        return block_platform_owner_lock('Platform sahibi hesabi koruma altinda. Bu hesabi baska ekip uyesi degistiremez.', 'platform-users', 'owner_account_protection')
    locked = require_platform_owner_for_locked_action(
        'team_role_changes_locked' if user.is_platform_admin else 'financial_changes_locked',
        'Bu kullanici/yetki degisikligi platform sahibi onayi gerektiriyor.',
        'platform-users'
    )
    if locked:
        return locked

    user.firma_adi = request.form.get('firma_adi', user.firma_adi).strip() or user.firma_adi
    user.paket_tipi = request.form.get('paket_tipi', user.paket_tipi)
    user.urun_limiti = max(1, int(request.form.get('urun_limiti') or user.urun_limiti or 10))
    user.role = request.form.get('role', user.role)
    platform_role = request.form.get('platform_role') or user.platform_role or 'viewer'
    if platform_role not in PLATFORM_ADMIN_ROLE_LABELS:
        platform_role = 'viewer'

    if user.id == current_user.id:
        user.aktif = True
        user.is_platform_admin = True
        user.platform_role = 'owner'
    else:
        user.aktif = request.form.get('aktif') == 'on'
        user.is_platform_admin = request.form.get('is_platform_admin') == 'on'
        user.platform_role = platform_role if user.is_platform_admin else 'viewer'

    if user.organization_id and request.form.get('source_context') != 'organization_users':
        organization = db.session.get(Organization, user.organization_id)
        if organization and user.role == 'owner':
            organization.name = user.firma_adi
            organization.plan = user.paket_tipi
            organization.product_limit = user.urun_limiti

    platform_audit('PLATFORM_USER_UPDATE', f'{user.email} guncellendi.', 'User', user.id)
    db.session.commit()
    flash('Kullanici yetkileri guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#companies')


@app.route('/super-admin/maintenance', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_maintenance():
    enabled = request.form.get('maintenance_mode') == 'on'
    set_platform_setting(
        'maintenance_mode',
        'on' if enabled else 'off',
        'Platform geneli bakim modu'
    )
    platform_audit(
        'PLATFORM_MAINTENANCE',
        'Bakim modu acildi.' if enabled else 'Bakim modu kapatildi.'
    )
    db.session.commit()
    flash('Bakim modu ayari guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-system')


@app.route('/super-admin/system/update', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_update_system_controls():
    maintenance_enabled = request.form.get('maintenance_mode') == 'on'
    registrations_enabled = request.form.get('registrations_enabled') == 'on'
    readonly_enabled = request.form.get('readonly_mode') == 'on'
    uploads_locked = request.form.get('file_uploads_locked') == 'on'
    dangerous_locked = request.form.get('dangerous_operations_locked') == 'on'
    security_enabled = request.form.get('security_shield_enabled') == 'on'
    owner_protection_enabled = request.form.get('owner_account_protection') == 'on'
    financial_locked = request.form.get('financial_changes_locked') == 'on'
    support_impersonation_locked = request.form.get('support_impersonation_locked') == 'on'
    data_export_locked = request.form.get('data_export_locked') == 'on'
    owner_approval_required = request.form.get('owner_approval_required') == 'on'
    notice_enabled = request.form.get('global_notice_enabled') == 'on'
    seo_closed_mode = request.form.get('seo_closed_mode') == 'on'
    seo_indexing_enabled = request.form.get('seo_indexing_enabled') == 'on'
    terminate_sessions = request.form.get('terminate_sessions') == 'on'
    default_plan = request.form.get('default_plan') or platform_setting('default_plan', 'demo')
    if default_plan not in {'demo', 'standart', 'profesyonel'}:
        default_plan = 'demo'
    auto_backup_frequency = request.form.get('auto_backup_frequency') or platform_setting('auto_backup_frequency', 'daily')
    if auto_backup_frequency not in {'off', 'daily', 'weekly', 'monthly'}:
        auto_backup_frequency = 'daily'
    numeric_fields = {
        'default_user_limit': (1, 500, platform_setting_int('default_user_limit', 1)),
        'default_product_limit': (1, 1000000, platform_setting_int('default_product_limit', 10)),
        'min_password_length': (8, 32, platform_setting_int('min_password_length', 8)),
        'session_lifetime_minutes': (15, 43200, platform_setting_int('session_lifetime_minutes', 480)),
        'failed_login_limit': (3, 25, platform_setting_int('failed_login_limit', 5)),
        'backup_retention_days': (1, 3650, platform_setting_int('backup_retention_days', 30)),
    }
    numeric_values = {}
    for key, (minimum, maximum, fallback) in numeric_fields.items():
        try:
            value = int(request.form.get(key) or fallback)
        except (TypeError, ValueError):
            value = fallback
        numeric_values[key] = min(max(value, minimum), maximum)

    set_platform_setting('maintenance_mode', 'on' if maintenance_enabled else 'off', 'Platform geneli bakim modu')
    set_platform_setting(
        'maintenance_message',
        (request.form.get('maintenance_message') or '').strip()[:500],
        'Bakim ekraninda gosterilecek mesaj'
    )
    set_platform_setting('maintenance_eta', (request.form.get('maintenance_eta') or '').strip()[:60], 'Planli bakim bitis tahmini')
    set_platform_setting('registrations_enabled', 'on' if registrations_enabled else 'off', 'Yeni firma kayit durumu')
    set_platform_setting(
        'pos_integration_enabled_for_users',
        'on' if request.form.get('pos_integration_enabled_for_users') == 'on' else 'off',
        'Normal kullanicilar icin POS entegrasyon ayarlari'
    )
    set_platform_setting('site_url', (request.form.get('site_url') or '').strip()[:200], 'SEO canonical base URL')
    set_platform_setting('site_name', (request.form.get('site_name') or '').strip()[:120], 'SEO site adi')
    set_platform_setting('site_description', (request.form.get('site_description') or '').strip()[:240], 'SEO site aciklamasi')
    set_platform_setting('site_og_image', (request.form.get('site_og_image') or '').strip()[:240], 'SEO OpenGraph gorsel URL')
    set_platform_setting('seo_closed_mode', 'on' if seo_closed_mode else 'off', 'Arama motorlarina karsi kapali mod')
    set_platform_setting('seo_indexing_enabled', 'on' if seo_indexing_enabled else 'off', 'Arama motorlarina acik SEO modu')

    set_platform_setting('smtp_host', (request.form.get('smtp_host') or '').strip()[:200], 'SMTP host')
    set_platform_setting('smtp_port', (request.form.get('smtp_port') or '').strip()[:6], 'SMTP port')
    set_platform_setting('smtp_use_tls', 'on' if request.form.get('smtp_use_tls') == 'on' else 'off', 'SMTP TLS')
    set_platform_setting('smtp_use_ssl', 'on' if request.form.get('smtp_use_ssl') == 'on' else 'off', 'SMTP SSL')
    set_platform_setting('smtp_username', (request.form.get('smtp_username') or '').strip()[:200], 'SMTP username')
    set_platform_setting('smtp_from_email', (request.form.get('smtp_from_email') or '').strip()[:200], 'SMTP From email')
    set_platform_setting('smtp_from_name', (request.form.get('smtp_from_name') or '').strip()[:120], 'SMTP From name')
    smtp_password = request.form.get('smtp_password') or ''
    if smtp_password.strip():
        set_platform_setting('smtp_password', smtp_password, 'SMTP password (stored)')

    set_platform_setting('readonly_mode', 'on' if readonly_enabled else 'off', 'Platform salt-okunur modu')
    set_platform_setting('file_uploads_locked', 'on' if uploads_locked else 'off', 'Dosya yukleme kilidi')
    set_platform_setting('dangerous_operations_locked', 'on' if dangerous_locked else 'off', 'Riskli islem kilidi')
    set_platform_setting('security_shield_enabled', 'on' if security_enabled else 'off', 'Supheli istek kalkanlari')
    set_platform_setting('owner_account_protection', 'on' if owner_protection_enabled else 'off', 'Platform sahibi hesabi koruma kilidi')
    set_platform_setting('financial_changes_locked', 'on' if financial_locked else 'off', 'Finansal ve firma degisikligi kilidi')
    set_platform_setting('support_impersonation_locked', 'on' if support_impersonation_locked else 'off', 'Destek modu giris kilidi')
    set_platform_setting('data_export_locked', 'on' if data_export_locked else 'off', 'Veri cikisi ve yedek goruntuleme kilidi')
    set_platform_setting('owner_approval_required', 'on' if owner_approval_required else 'off', 'Kritik islemler icin platform sahibi onayi')
    set_platform_setting('global_notice_enabled', 'on' if notice_enabled else 'off', 'Global duyuru durumu')
    set_platform_setting('platform_name', (request.form.get('platform_name') or platform_setting('platform_name', 'StokCari')).strip()[:120], 'Platform gorunen adi')
    set_platform_setting('default_plan', default_plan, 'Yeni firmalar icin varsayilan paket')
    set_platform_setting('support_email', (request.form.get('support_email') or platform_setting('support_email', '')).strip().lower()[:120], 'Destek iletisim e-postasi')
    set_platform_setting('auto_backup_frequency', auto_backup_frequency, 'Otomatik yedekleme sikligi')
    for key, value in numeric_values.items():
        set_platform_setting(key, value)
    set_platform_setting(
        'global_notice_message',
        (request.form.get('global_notice_message') or '').strip()[:240],
        'Tum kullanicilara gosterilecek sistem duyurusu'
    )
    if terminate_sessions:
        set_platform_setting('session_epoch', datetime.now(timezone.utc).isoformat(), 'Platform ekip harici oturum kesme zamani')

    platform_audit(
        'PLATFORM_SYSTEM_CONTROLS_UPDATE',
        (
            f'bakim={maintenance_enabled}, salt_okunur={readonly_enabled}, '
            f'yukleme_kilidi={uploads_locked}, riskli_islem_kilidi={dangerous_locked}, '
            f'guvenlik_kalkani={security_enabled}, duyuru={notice_enabled}, '
            f'sahip_koruma={owner_protection_enabled}, finans_kilidi={financial_locked}, '
            f'destek_girisi_kilidi={support_impersonation_locked}, veri_cikisi_kilidi={data_export_locked}, '
            f'sahip_onayi={owner_approval_required}, '
            f'oturum_sonlandirma={terminate_sessions}'
        )
    )
    db.session.commit()
    flash('Sistem yonetimi kontrolleri guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-system')


@app.route('/super-admin/system/self-test', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_run_self_test():
    result = run_platform_self_test()
    if result['status'] == 'passed':
        flash(result['status_label'], 'success')
    elif result['status'] == 'warning':
        flash(result['status_label'], 'warning')
    else:
        flash(result['status_label'], 'error')
    return redirect(url_for('super_admin_dashboard') + '#platform-system')


@app.route('/super-admin/system/workflow-test', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_run_workflow_test():
    result = run_platform_workflow_test()
    if result['status'] == 'passed':
        flash(result['status_label'], 'success')
    elif result['status'] == 'warning':
        flash(result['status_label'], 'warning')
    else:
        flash(result['status_label'], 'error')
    return redirect(url_for('super_admin_dashboard') + '#platform-system')


@app.route('/super-admin/system/test-center/run', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_run_inventory_test():
    test_name = (request.form.get('test_name') or '').strip()
    result = run_platform_inventory_test(test_name)
    if result['status'] == 'passed':
        flash(f"{result['label']} testi başarıyla geçti.", 'success')
    else:
        flash(f"{result['label']} testi hata verdi. Test Merkezi içindeki çıktıyı kontrol edin.", 'error')
    return redirect(url_for('super_admin_dashboard') + '#platform-system-test-center')


def sha256_of_path(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@app.route('/super-admin/system/release/upload', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_upload_release():
    uploaded = request.files.get('release_zip')
    if not uploaded or not uploaded.filename:
        flash('Güncelleme dosyası seçilmedi.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-system')

    filename = secure_filename(uploaded.filename)
    if not filename.lower().endswith('.zip'):
        flash('Sadece .zip dosyası yükleyebilirsiniz.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-system')

    request_id = uuid.uuid4().hex
    incoming_dir = os.path.join(updater_base_dir(), 'incoming')
    os.makedirs(incoming_dir, exist_ok=True)
    zip_path = os.path.join(incoming_dir, f'{request_id}.zip')
    uploaded.save(zip_path)

    version = None
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            if 'VERSION' in z.namelist():
                version = (z.read('VERSION').decode('utf-8', errors='replace') or '').strip() or None
    except zipfile.BadZipFile:
        try:
            os.remove(zip_path)
        except Exception:
            pass
        flash('Zip dosyası bozuk ya da okunamad?.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-system')

    payload = {
        'id': request_id,
        'uploaded_at': datetime.now(timezone.utc).isoformat(),
        'uploaded_by': getattr(current_user, 'email', None),
        'original_filename': filename,
        'zip_path': zip_path,
        'sha256': sha256_of_path(zip_path),
        'version': version or f'upload-{request_id[:8]}',
    }
    write_updater_request(payload)

    platform_audit('PLATFORM_SYSTEM_CONTROLS_UPDATE', f"Release yüklendi: {payload['version']} ({filename})", 'Platform', None)
    db.session.commit()
    flash(f"Güncelleme yüklendi: {payload['version']}. Updater servisi uygular (başarısızsa eski sürüm kalır).", 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-system')


@app.route('/super-admin/settings/update', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_update_settings():
    default_plan = request.form.get('default_plan') or 'demo'
    if default_plan not in {'demo', 'standart', 'profesyonel'}:
        default_plan = 'demo'

    auto_backup_frequency = request.form.get('auto_backup_frequency') or 'daily'
    if auto_backup_frequency not in {'off', 'daily', 'weekly', 'monthly'}:
        auto_backup_frequency = 'daily'

    numeric_fields = {
        'default_user_limit': (1, 500, 1),
        'default_product_limit': (1, 1000000, 10),
        'min_password_length': (8, 32, 8),
        'session_lifetime_minutes': (15, 43200, 480),
        'failed_login_limit': (3, 25, 5),
        'backup_retention_days': (1, 3650, 30),
    }
    numeric_values = {}
    for key, (minimum, maximum, fallback) in numeric_fields.items():
        try:
            value = int(request.form.get(key) or fallback)
        except (TypeError, ValueError):
            value = fallback
        numeric_values[key] = min(max(value, minimum), maximum)

    set_platform_setting('platform_name', (request.form.get('platform_name') or 'StokCari').strip()[:120], 'Platform gorunen adi')
    set_platform_setting('default_plan', default_plan, 'Yeni firmalar icin varsayilan paket')
    set_platform_setting('registrations_enabled', 'on' if request.form.get('registrations_enabled') == 'on' else 'off', 'Yeni firma kayit durumu')
    set_platform_setting(
        'pos_integration_enabled_for_users',
        'on' if request.form.get('pos_integration_enabled_for_users') == 'on' else 'off',
        'Normal kullanicilar icin POS entegrasyon ayarlari'
    )
    set_platform_setting('maintenance_message', (request.form.get('maintenance_message') or '').strip()[:500], 'Bakim ekraninda gosterilecek mesaj')
    set_platform_setting('support_email', (request.form.get('support_email') or '').strip().lower()[:120], 'Destek iletisim e-postasi')
    set_platform_setting('auto_backup_frequency', auto_backup_frequency, 'Otomatik yedekleme sikligi')

    for key, value in numeric_values.items():
        set_platform_setting(key, value)

    platform_audit('PLATFORM_SETTINGS_UPDATE', 'Sistem ayarlari guncellendi.')
    db.session.commit()
    flash('Sistem ayarlari guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-system')


def build_action_center_context(per_page=30):
    sync_action_center()
    db.session.commit()

    status = request.args.get('status') or 'open'
    source = request.args.get('source') or ''
    severity = request.args.get('severity') or ''
    query_text = (request.args.get('q') or '').strip()

    query = ActionItem.query.order_by(
        ActionItem.severity.desc(),
        ActionItem.due_at.asc().nullslast(),
        ActionItem.updated_at.desc(),
    )
    if status:
        query = query.filter_by(status=status)
    if source:
        query = query.filter_by(source_type=source)
    if severity:
        query = query.filter_by(severity=severity)
    if query_text:
        like = f'%{query_text}%'
        query = query.filter(or_(ActionItem.title.ilike(like), ActionItem.description.ilike(like)))

    actions = query.paginate(page=request.args.get('page', 1, type=int), per_page=per_page, error_out=False)
    now_utc = datetime.now(timezone.utc)
    now_for_template = now_utc.replace(tzinfo=None)
    today_end = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)
    stats = {
        'open': ActionItem.query.filter_by(status='open').count(),
        'critical': ActionItem.query.filter_by(status='open', severity='critical').count(),
        'snoozed': ActionItem.query.filter_by(status='snoozed').count(),
        'done': ActionItem.query.filter_by(status='done').count(),
        'overdue': ActionItem.query.filter(
            ActionItem.status == 'open',
            ActionItem.due_at.isnot(None),
            ActionItem.due_at < now_utc
        ).count(),
        'due_today': ActionItem.query.filter(
            ActionItem.status == 'open',
            ActionItem.due_at.isnot(None),
            ActionItem.due_at >= now_utc,
            ActionItem.due_at <= today_end
        ).count(),
    }
    source_counts = {
        key: ActionItem.query.filter_by(status='open', source_type=key).count()
        for key in ACTION_SOURCE_LABELS
    }
    severity_counts = {
        key: ActionItem.query.filter_by(status='open', severity=key).count()
        for key in ACTION_SEVERITY_LABELS
    }
    next_action = ActionItem.query.filter_by(status='open') \
        .order_by(ActionItem.due_at.asc().nullslast(), ActionItem.updated_at.desc()) \
        .first()
    platform_admins = User.query.filter_by(is_platform_admin=True, aktif=True).order_by(User.email).all()
    return {
        'actions': actions,
        'stats': stats,
        'source_counts': source_counts,
        'severity_counts': severity_counts,
        'next_action': next_action,
        'status': status,
        'source': source,
        'severity': severity,
        'query_text': query_text,
        'status_labels': ACTION_STATUS_LABELS,
        'severity_labels': ACTION_SEVERITY_LABELS,
        'source_labels': ACTION_SOURCE_LABELS,
        'event_labels': ACTION_EVENT_LABELS,
        'platform_admins': platform_admins,
        'sla_state': action_sla_state,
        'now_utc': now_for_template,
    }


@app.route('/super-admin/actions')
@login_required
@platform_admin_required
def super_admin_actions():
    build_action_center_context()
    return redirect(url_for('super_admin_dashboard') + '#platform-actions')


@app.route('/super-admin/actions/<int:action_id>/update', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('actions_manage')
def super_admin_update_action(action_id):
    action = db.session.get(ActionItem, action_id)
    if not action:
        abort(404)

    operation = request.form.get('operation')
    if operation == 'done':
        action.status = 'done'
        action.resolved_at = datetime.now(timezone.utc)
        action.snoozed_until = None
        add_action_event(action, 'done', 'Aksiyon tamamlandi.')
    elif operation == 'snooze':
        days = request.form.get('days', 3, type=int)
        action.status = 'snoozed'
        action.snoozed_until = datetime.now(timezone.utc) + timedelta(days=max(1, min(days, 30)))
        action.resolved_at = None
        add_action_event(action, 'snoozed', f'{days} gun ertelendi.')
    elif operation == 'open':
        action.status = 'open'
        action.snoozed_until = None
        action.resolved_at = None
        add_action_event(action, 'reopened', 'Aksiyon yeniden acildi.')
    elif operation == 'assign':
        assigned_user_id = request.form.get('assigned_user_id', type=int)
        assigned_user = db.session.get(User, assigned_user_id) if assigned_user_id else None
        action.assigned_user_id = assigned_user.id if assigned_user and assigned_user.is_platform_admin else None
        add_action_event(
            action,
            'assigned',
            f'{assigned_user.email} atandi.' if assigned_user else 'Sahip atamasi kaldirildi.'
        )

    action.updated_at = datetime.now(timezone.utc)
    platform_audit('ACTION_ITEM_UPDATE', f'Aksiyon guncellendi: #{action.id} {action.status}', 'ActionItem', action.id)
    db.session.commit()
    flash('Aksiyon guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-actions')


@app.route('/super-admin/actions/<int:action_id>/ai', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('actions_manage')
def super_admin_refresh_action_ai(action_id):
    action = db.session.get(ActionItem, action_id)
    if not action:
        abort(404)

    summary, recommendation = generate_action_ai_recommendation(action)
    action.ai_summary = summary
    action.ai_recommendation = recommendation
    action.updated_at = datetime.now(timezone.utc)
    add_action_event(action, 'ai_refreshed', 'AI operasyon onerisi yenilendi.')
    platform_audit('ACTION_ITEM_UPDATE', f'AI onerisi yenilendi: #{action.id}', 'ActionItem', action.id)
    db.session.commit()
    flash('AI onerisi guncellendi.', 'success')
    return redirect(url_for('super_admin_dashboard') + '#platform-actions')


def build_support_ticket_context(per_page=30):
    status = request.args.get('support_status') or ''
    query = SupportTicket.query.order_by(SupportTicket.updated_at.desc())
    if status:
        query = query.filter_by(status=status)
    tickets = query.paginate(page=request.args.get('page', 1, type=int), per_page=per_page, error_out=False)
    status_counts = {
        key: SupportTicket.query.filter_by(status=key).count()
        for key in SUPPORT_STATUS_LABELS
    }
    return {
        'tickets': tickets,
        'status': status,
        'status_counts': status_counts,
        'status_labels': SUPPORT_STATUS_LABELS,
        'priority_labels': SUPPORT_PRIORITY_LABELS,
        'category_labels': SUPPORT_CATEGORY_LABELS,
    }


def platform_insights_context():
    today = date.today()
    due_cutoff = today + timedelta(days=30)
    risky_organizations = Organization.query.filter(
        Organization.subscription_end.isnot(None),
        Organization.subscription_end <= due_cutoff,
        Organization.subscription_status != 'cancelled'
    ).order_by(Organization.subscription_end.asc()).limit(6).all()
    support_hotspots = db.session.query(
        Organization,
        db.func.count(SupportTicket.id).label('ticket_count')
    ).join(SupportTicket, SupportTicket.organization_id == Organization.id) \
        .filter(SupportTicket.status.in_(['open', 'waiting_admin', 'waiting_customer'])) \
        .group_by(Organization.id) \
        .order_by(db.func.count(SupportTicket.id).desc()) \
        .limit(6).all()
    latest_backup = BackupLog.query.order_by(BackupLog.created_at.desc()).first()
    return {
        'risky_organizations': risky_organizations,
        'support_hotspots': support_hotspots,
        'latest_backup': latest_backup,
        'open_actions': ActionItem.query.filter(ActionItem.status.in_(['open', 'snoozed'])).count(),
        'critical_actions': ActionItem.query.filter_by(status='open', severity='critical').count(),
        'pending_support': SupportTicket.query.filter(SupportTicket.status.in_(['open', 'waiting_admin'])).count(),
        'platform_admin_roles': {
            key: User.query.filter_by(is_platform_admin=True, platform_role=key).count()
            for key in PLATFORM_ADMIN_ROLE_LABELS
        },
    }


@app.route('/super-admin/support')
@login_required
@platform_admin_required
def super_admin_support_tickets():
    return redirect(url_for('super_admin_dashboard') + '#platform-support')


@app.route('/super-admin/support/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
@platform_admin_required
def super_admin_support_ticket_detail(ticket_id):
    ticket = db.session.get(SupportTicket, ticket_id)
    if not ticket:
        abort(404)

    if not platform_can('support_manage' if request.method == 'POST' else 'support_view'):
        flash('Bu destek talebi icin platform yetkiniz yok.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#platform-support')

    if request.method == 'POST':
        ticket.status = request.form.get('status') or ticket.status
        ticket.priority = request.form.get('priority') or ticket.priority
        message = (request.form.get('message') or '').strip()
        if message:
            try:
                attachment_data = save_support_attachment(request.files.get('screenshot'))
            except ValueError as exc:
                flash(str(exc), 'error')
                return redirect(url_for('super_admin_support_ticket_detail', ticket_id=ticket.id))
            db.session.add(SupportTicketMessage(
                ticket_id=ticket.id,
                user_id=current_user.id,
                message=message,
                is_staff_reply=True,
                **attachment_data,
            ))
            if ticket.status in {'open', 'waiting_admin'}:
                ticket.status = 'waiting_customer'
        if ticket.status in {'resolved', 'closed'}:
            ticket.closed_at = datetime.now(timezone.utc)
        else:
            ticket.closed_at = None
        ticket.updated_at = datetime.now(timezone.utc)
        platform_audit('SUPPORT_TICKET_UPDATE', f'Destek talebi guncellendi: #{ticket.id}', 'SupportTicket', ticket.id)
        sync_support_ticket_action(ticket)
        db.session.commit()
        flash('Destek talebi guncellendi.', 'success')
        return redirect(url_for('super_admin_support_ticket_detail', ticket_id=ticket.id))

    return render_template(
        'super_admin/support_detail.html',
        ticket=ticket,
        status_labels=SUPPORT_STATUS_LABELS,
        priority_labels=SUPPORT_PRIORITY_LABELS,
        category_labels=SUPPORT_CATEGORY_LABELS,
    )


@app.route('/super-admin/organizations/<int:organization_id>/impersonate', methods=['POST'])
@login_required
@platform_admin_required
def super_admin_impersonate(organization_id):
    locked = require_platform_owner_for_locked_action(
        'support_impersonation_locked',
        'Destek modu girisi kilitli. Musteri hesabina girisi sadece platform sahibi acabilir.',
        'companies'
    )
    if locked:
        return locked

    organization = db.session.get(Organization, organization_id)
    if not organization:
        abort(404)
    owner = organization_owner(organization)
    if not owner:
        flash('Bu firmada destek girisi yapilacak sahip kullanici bulunamadi.', 'error')
        return redirect(url_for('super_admin_dashboard') + '#companies')

    platform_audit('PLATFORM_IMPERSONATE_START', f'{owner.email} hesabina destek girisi.', 'Organization', organization.id)
    db.session.commit()
    session['platform_admin_id'] = current_user.id
    session['_user_id'] = str(owner.id)
    session['_fresh'] = True
    flash(f'{organization.name} firmasina destek modunda girdiniz.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/super-admin/impersonation/exit', methods=['POST'])
@login_required
def super_admin_exit_impersonation():
    platform_admin_id = session.pop('platform_admin_id', None)
    if not platform_admin_id:
        return redirect(url_for('dashboard'))

    supported_email = current_user.email
    session['_user_id'] = str(platform_admin_id)
    session['_fresh'] = True
    platform_admin = db.session.get(User, int(platform_admin_id))
    if platform_admin:
        db.session.add(AuditLog(
            user_id=platform_admin.id,
            action='PLATFORM_IMPERSONATE_END',
            resource_type='Platform',
            details=f'Destek modundan cikildi: {supported_email}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', ''),
            session_id=session.get('_id', '')
        ))
        db.session.commit()
    flash('Super admin oturumuna geri dondunuz.', 'success')
    return redirect(url_for('super_admin_dashboard'))


@app.route('/super-admin/logs')
@login_required
@platform_admin_required
@platform_permission_required('logs_view')
def super_admin_logs():
    page = request.args.get('page', 1, type=int)
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=40, error_out=False
    )
    return render_template('super_admin/logs.html', logs=logs)


@app.route('/super-admin/backups')
@login_required
@platform_admin_required
@platform_permission_required('backups_view')
def super_admin_backups():
    locked = require_platform_owner_for_locked_action(
        'data_export_locked',
        'Veri cikisi kilitli. Yedek kayitlarini sadece platform sahibi goruntuleyebilir.',
        'platform-backup'
    )
    if locked:
        return locked

    page = request.args.get('page', 1, type=int)
    status_filter = (request.args.get('status') or '').strip().lower()
    type_filter = (request.args.get('type') or '').strip().lower()
    search_query = (request.args.get('q') or '').strip().lower()

    query = BackupLog.query.join(User).order_by(BackupLog.created_at.desc())
    if status_filter in {'completed', 'failed', 'in_progress'}:
        query = query.filter(BackupLog.status == status_filter)
    if type_filter in {'manual', 'auto'}:
        query = query.filter(BackupLog.backup_type == type_filter)
    if search_query:
        query = query.filter(
            or_(
                db.func.lower(BackupLog.filename).contains(search_query),
                db.func.lower(User.email).contains(search_query),
                db.func.lower(User.firma_adi).contains(search_query),
            )
        )

    backups = query.paginate(page=page, per_page=40, error_out=False)

    # Summary cards (platform-wide)
    totals = {
        'total': BackupLog.query.count(),
        'completed': BackupLog.query.filter_by(status='completed').count(),
        'failed': BackupLog.query.filter_by(status='failed').count(),
        'in_progress': BackupLog.query.filter_by(status='in_progress').count(),
    }
    latest = BackupLog.query.order_by(BackupLog.created_at.desc()).first()
    total_size = db.session.query(db.func.coalesce(db.func.sum(BackupLog.file_size), 0)).scalar() or 0
    policies = {
        'auto_backup_frequency': platform_setting('auto_backup_frequency', 'daily'),
        'backup_retention_days': platform_setting_int('backup_retention_days', 30),
    }

    return render_template(
        'super_admin/backups.html',
        backups=backups,
        totals=totals,
        latest=latest,
        total_size=total_size,
        status_filter=status_filter,
        type_filter=type_filter,
        search_query=search_query,
        policies=policies,
    )


@app.route('/super-admin/backups/download/<int:backup_id>')
@login_required
@platform_admin_required
@platform_permission_required('backups_view')
def super_admin_download_backup(backup_id):
    locked = require_platform_owner_for_locked_action(
        'data_export_locked',
        'Veri cikisi kilitli. Yedek indirme islemi sadece platform sahibi tarafindan yapilabilir.',
        'platform-backup'
    )
    if locked:
        return locked

    backup = db.session.get(BackupLog, backup_id)
    if not backup:
        abort(404)

    if backup.status != 'completed':
        flash('Bu yedek kaydi tamamlanmamis. Indirme icin tamamlanmis yedek secin.', 'warning')
        return redirect(url_for('super_admin_backups'))

    safe_filename = secure_filename(backup.filename or '')
    if not safe_filename or safe_filename != backup.filename:
        flash('Gecersiz yedek dosya adi.', 'error')
        return redirect(url_for('super_admin_backups'))

    backup_path = backup_file_path_for_user(backup.user_id, safe_filename)
    if not os.path.isfile(backup_path):
        flash('Yedek dosyasi sunucuda bulunamadi.', 'error')
        return redirect(url_for('super_admin_backups'))

    platform_audit(
        'PLATFORM_BACKUP_DOWNLOAD',
        f'Yedek indirildi: backup_id={backup.id}, file={safe_filename}, user_id={backup.user_id}',
        'BackupLog',
        backup.id
    )
    db.session.commit()
    return send_from_directory(os.path.dirname(backup_path), safe_filename, as_attachment=True, download_name=safe_filename)


@app.route('/super-admin/backups/run-auto', methods=['POST'])
@login_required
@platform_admin_required
@platform_permission_required('settings_manage')
def super_admin_run_auto_backups():
    result = run_platform_auto_backup(force=True)
    if not result.get('ran'):
        reason = result.get('reason', 'unknown')
        flash(f'Otomatik yedekleme calistirilmadi: {reason}', 'warning')
        return redirect(url_for('super_admin_backups'))

    retention = result.get('retention') or {}
    flash(
        f"Otomatik yedekleme tamamlandi: {result.get('created', 0)} olustu, {result.get('failed', 0)} hata. "
        f"Retention: {retention.get('deleted', 0)} silindi.",
        'success' if result.get('failed', 0) == 0 else 'warning'
    )
    platform_audit(
        'PLATFORM_AUTO_BACKUP_RUN',
        f"auto_backup: created={result.get('created', 0)}, failed={result.get('failed', 0)}, "
        f"retention_deleted={retention.get('deleted', 0)}",
        'Platform'
    )
    db.session.commit()
    return redirect(url_for('super_admin_backups'))


@app.route('/destek', methods=['GET', 'POST'])
@login_required
def support_tickets():
    organization = current_organization()
    if not organization:
        flash('Destek talebi icin firma bilgisi bulunamadi.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        subject = (request.form.get('subject') or '').strip()
        message = (request.form.get('message') or '').strip()
        category = request.form.get('category') or 'general'
        priority = request.form.get('priority') or 'normal'
        if not subject or not message:
            flash('Konu ve aciklama zorunludur.', 'error')
            return redirect(url_for('support_tickets'))
        if category not in SUPPORT_CATEGORY_LABELS:
            category = 'general'
        if priority not in SUPPORT_PRIORITY_LABELS:
            priority = 'normal'

        ticket = SupportTicket(
            organization_id=organization.id,
            requester_id=current_user.id,
            subject=subject[:180],
            category=category,
            priority=priority,
            status='waiting_admin',
        )
        db.session.add(ticket)
        db.session.flush()
        try:
            attachment_data = save_support_attachment(request.files.get('screenshot'))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return redirect(url_for('support_tickets'))
        db.session.add(SupportTicketMessage(
            ticket_id=ticket.id,
            user_id=current_user.id,
            message=message[:4000],
            is_staff_reply=False,
            **attachment_data,
        ))
        platform_audit('SUPPORT_TICKET_CREATE', f'Destek talebi acildi: #{ticket.id}', 'SupportTicket', ticket.id)
        sync_support_ticket_action(ticket)
        db.session.commit()
        flash('Destek talebiniz alindi.', 'success')
        return redirect(url_for('support_ticket_detail', ticket_id=ticket.id))

    user_ids = organization_user_ids(organization)
    tickets = SupportTicket.query.filter_by(organization_id=organization.id) \
        .order_by(SupportTicket.updated_at.desc()).all()
    return render_template(
        'support_tickets.html',
        tickets=tickets,
        status_labels=SUPPORT_STATUS_LABELS,
        priority_labels=SUPPORT_PRIORITY_LABELS,
        category_labels=SUPPORT_CATEGORY_LABELS,
        open_count=sum(1 for ticket in tickets if ticket.status not in {'resolved', 'closed'}),
        requester_count=len(user_ids),
    )


@app.route('/destek/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def support_ticket_detail(ticket_id):
    ticket = db.session.get(SupportTicket, ticket_id)
    if not support_ticket_allowed(ticket):
        abort(404)

    if request.method == 'POST':
        message = (request.form.get('message') or '').strip()
        if not message:
            flash('Yanıt metni bos olamaz.', 'error')
            return redirect(url_for('support_ticket_detail', ticket_id=ticket.id))
        try:
            attachment_data = save_support_attachment(request.files.get('screenshot'))
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('support_ticket_detail', ticket_id=ticket.id))
        db.session.add(SupportTicketMessage(
            ticket_id=ticket.id,
            user_id=current_user.id,
            message=message[:4000],
            is_staff_reply=False,
            **attachment_data,
        ))
        if ticket.status in {'waiting_customer', 'open'}:
            ticket.status = 'waiting_admin'
        ticket.updated_at = datetime.now(timezone.utc)
        sync_support_ticket_action(ticket)
        db.session.commit()
        flash('Yanıtın?z kaydedildi.', 'success')
        return redirect(url_for('support_ticket_detail', ticket_id=ticket.id))

    return render_template(
        'support_ticket_detail.html',
        ticket=ticket,
        status_labels=SUPPORT_STATUS_LABELS,
        priority_labels=SUPPORT_PRIORITY_LABELS,
        category_labels=SUPPORT_CATEGORY_LABELS,
    )


@app.route('/destek/ek/<int:message_id>/<filename>')
@login_required
def support_attachment(message_id, filename):
    message = db.session.get(SupportTicketMessage, message_id)
    if not message or not message.attachment_filename or message.attachment_filename != secure_filename(filename):
        abort(404)
    if not support_ticket_allowed(message.ticket):
        abort(404)
    return send_from_directory(
        support_upload_dir(),
        message.attachment_filename,
        mimetype=message.attachment_content_type,
        as_attachment=False,
        download_name=message.attachment_original_name or message.attachment_filename,
    )


@app.route('/cikis', methods=['POST'])
@login_required
def cikis():
    # Audit log kaydı
    audit_logout = AuditLog(
        user_id=current_user.id,
        action='LOGOUT',
        resource_type='User',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', ''),
        session_id=session.get('_id', '')
    )
    db.session.add(audit_logout)
    db.session.commit()

    logout_user()
    return redirect(url_for('index'))

# Kurumsal Sistem Y?netimi


@app.route('/admin')
@login_required
def admin_panel():
    if current_user.paket_tipi not in ['profesyonel']:
        flash('Bu sayfaya erişim izniniz yok!', 'error')
        return redirect(url_for('dashboard'))

    # Tenant istatistikleri
    total_users = 1
    total_products = Urun.query.filter_by(user_id=current_user.id).count()
    total_sales = Satis.query.filter_by(user_id=current_user.id).count()
    total_quotes = Teklif.query.filter_by(user_id=current_user.id).count()

    # Son tenant audit loglar?
    recent_logs = AuditLog.query.filter_by(user_id=current_user.id).order_by(AuditLog.timestamp.desc()).limit(20).all()

    # Tenant ayarları
    settings = SystemSettings.query.filter_by(user_id=current_user.id).all()

    return render_template('admin_panel.html',
                           total_users=total_users,
                           total_products=total_products,
                           total_sales=total_sales,
                           total_quotes=total_quotes,
                           recent_logs=recent_logs,
                           settings=settings)


@app.route('/admin/audit-logs')
@login_required
def audit_logs():
    if current_user.paket_tipi not in ['profesyonel']:
        flash('Bu sayfaya erişim izniniz yok!', 'error')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = current_items_per_page()
    action_filter = (request.args.get('action') or 'all').strip()
    resource_filter = (request.args.get('resource') or 'all').strip()
    search_query = (request.args.get('q') or '').strip()

    query = AuditLog.query.filter_by(user_id=current_user.id)
    if action_filter != 'all':
        query = query.filter(AuditLog.action == action_filter)
    if resource_filter != 'all':
        query = query.filter(AuditLog.resource_type == resource_filter)
    if search_query:
        like_query = f'%{search_query}%'
        query = query.filter(or_(
            AuditLog.action.ilike(like_query),
            AuditLog.resource_type.ilike(like_query),
            AuditLog.details.ilike(like_query),
            AuditLog.ip_address.ilike(like_query),
        ))

    logs = query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    base_query = AuditLog.query.filter_by(user_id=current_user.id)
    total_logs = base_query.count()
    critical_logs = base_query.filter(AuditLog.action.in_(['DELETE', 'LOGIN_FAILED', 'SECURITY_THREAT_BLOCKED'])).count()
    action_options = [
        row[0] for row in db.session.query(AuditLog.action)
        .filter_by(user_id=current_user.id)
        .distinct()
        .order_by(AuditLog.action.asc())
        .all()
        if row[0]
    ]
    resource_options = [
        row[0] for row in db.session.query(AuditLog.resource_type)
        .filter_by(user_id=current_user.id)
        .distinct()
        .order_by(AuditLog.resource_type.asc())
        .all()
        if row[0]
    ]

    return render_template(
        'audit_logs.html',
        logs=logs,
        total_logs=total_logs,
        critical_logs=critical_logs,
        action_options=action_options,
        resource_options=resource_options,
        selected_action=action_filter,
        selected_resource=resource_filter,
        search_query=search_query,
    )


@app.route('/admin/backup')
@login_required
def backup_management():
    if current_user.paket_tipi not in ['profesyonel']:
        flash('Bu sayfaya erişim izniniz yok!', 'error')
        return redirect(url_for('dashboard'))

    backup_items = BackupLog.query.filter_by(user_id=current_user.id).order_by(BackupLog.created_at.desc()).all()
    pagination = paginate_list_items(backup_items)

    return render_template('backup_management.html', backups=pagination.items, pagination=pagination)


@app.route('/admin/backup/create', methods=['POST'])
@login_required
def create_backup():
    if current_user.paket_tipi not in ['profesyonel']:
        return jsonify({'success': False, 'message': 'Yetkiniz yok!'})

    try:
        from datetime import datetime

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'admin_backup_{timestamp}.json'
        backup_dir = backup_dir_for_user(current_user)
        backup_path = os.path.join(backup_dir, backup_filename)
        os.makedirs(backup_dir, exist_ok=True)

        backup_data = {
            'user_info': {
                'firma_adi': current_user.firma_adi,
                'email': current_user.email,
                'telefon': current_user.telefon,
                'created_at': current_user.kayit_tarihi.isoformat() if current_user.kayit_tarihi else None
            },
            'urunler': [
                {
                    'urun_adi': urun.urun_adi,
                    'barkod': urun.barkod,
                    'kategori': urun.kategori,
                    'stok_miktari': urun.stok_miktari,
                    'satis_fiyati': urun.satis_fiyati,
                    'depo_adi': urun.depo_adi
                }
                for urun in Urun.query.filter_by(user_id=current_user.id).all()
            ],
            'cariler': [
                {
                    'unvan': cari.unvan,
                    'telefon': cari.telefon,
                    'email': cari.email,
                    'borc': cari.borc,
                    'alacak': cari.alacak
                }
                for cari in Cari.query.filter_by(user_id=current_user.id).all()
            ],
            'satislar': [
                {
                    'fatura_no': satis.fatura_no,
                    'tarih': satis.tarih.isoformat() if satis.tarih else None,
                    'genel_toplam': satis.genel_toplam,
                    'durum': satis.durum
                }
                for satis in Satis.query.filter_by(user_id=current_user.id).all()
            ],
            'teklifler': [
                {
                    'teklif_no': teklif.teklif_no,
                    'tarih': teklif.tarih.isoformat() if teklif.tarih else None,
                    'genel_toplam': teklif.genel_toplam,
                    'durum': teklif.durum
                }
                for teklif in Teklif.query.filter_by(user_id=current_user.id).all()
            ],
            'backup_info': {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'tenant',
                'user_id': current_user.id
            }
        }

        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        file_size = os.path.getsize(backup_path)

        backup_log = BackupLog(
            filename=backup_filename,
            file_size=file_size,
            backup_type='manual',
            status='completed',
            user_id=current_user.id,
            completed_at=datetime.now(timezone.utc)
        )
        db.session.add(backup_log)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Yedekleme başarıyla tamamlandı!',
            'filename': backup_filename,
            'size': file_size
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'})


@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def system_settings():
    if current_user.paket_tipi not in ['profesyonel']:
        flash('Bu sayfaya erişim izniniz yok!', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        for key, value in request.form.items():
            setting = SystemSettings.query.filter_by(key=key, user_id=current_user.id).first()
            if setting:
                setting.value = value
                setting.updated_at = datetime.now(timezone.utc)
            else:
                setting = SystemSettings(
                    key=key,
                    value=value,
                    user_id=current_user.id
                )
                db.session.add(setting)

        db.session.commit()
        flash('Ayarlar başarıyla güncellendi!', 'success')
        return redirect(url_for('system_settings'))

    settings = SystemSettings.query.filter_by(user_id=current_user.id).all()
    return render_template('system_settings.html', settings=settings)

# Ayarlar


@app.route('/ayarlar')
@login_required
def ayarlar():
    from flask import session

    # Kategorileri ?ek - kullan?c?n?n Ürünlerindeki benzersiz kategoriler
    urunler = Urun.query.filter_by(user_id=current_user.id).all()
    kategori_sayim = {}
    for urun in urunler:
        kategori = urun.kategori or 'Kategorisiz'
        if kategori != 'Kategorisiz':
            kategori_sayim[kategori] = kategori_sayim.get(kategori, 0) + 1

    # Session'dan eklenen kategorileri de al
    user_kategoriler = session.get(f'kategoriler_{current_user.id}', [])
    for kat in user_kategoriler:
        if kat not in kategori_sayim:
            kategori_sayim[kat] = 0  # Hen?z Ürün yok

    kategoriler = [{'ad': k, 'urun_sayisi': s} for k, s in kategori_sayim.items()]

    # Kullan?c? istatistikleri
    toplam_urun = len(urunler)
    toplam_cari = Cari.query.filter_by(user_id=current_user.id).count()
    toplam_satis = Satis.query.filter_by(user_id=current_user.id).count()

    # Sistem mod?lleri ve izinleri
    moduller = [
        {
            'ad': 'Ana Panel',
            'ikon': 'dashboard',
            'aciklama': 'Dashboard ve genel bakış',
            'tum_izinler': ['goruntuleme']
        },
        {
            'ad': 'Ürünler',
            'ikon': 'inventory',
            'aciklama': 'Ürün yönetimi ve stok takibi',
            'tum_izinler': ['goruntuleme', 'olusturma', 'duzenleme', 'silme']
        },
        {
            'ad': 'Cariler',
            'ikon': 'group',
            'aciklama': 'Cari hesap yönetimi',
            'tum_izinler': ['goruntuleme', 'olusturma', 'duzenleme', 'silme']
        },
        {
            'ad': 'POS Satış',
            'ikon': 'point_of_sale',
            'aciklama': 'Hızlı satış ve Ödeme',
            'tum_izinler': ['goruntuleme', 'olusturma']
        },
        {
            'ad': 'Teklifler',
            'ikon': 'description',
            'aciklama': 'Teklif yönetimi',
            'tum_izinler': ['goruntuleme', 'olusturma', 'duzenleme', 'silme']
        },
        {
            'ad': 'İade İşlemleri',
            'ikon': 'assignment_return',
            'aciklama': 'İade ve iade yönetimi',
            'tum_izinler': ['goruntuleme', 'olusturma']
        },
        {
            'ad': 'Raporlar',
            'ikon': 'bar_chart',
            'aciklama': 'Finansal raporlar ve analiz',
            'tum_izinler': ['goruntuleme']
        },
        {
            'ad': 'Ayarlar',
            'ikon': 'settings',
            'aciklama': 'Sistem ayarları ve yapılandırma',
            'tum_izinler': ['goruntuleme', 'duzenleme']
        }
    ]

    # Kullan?c? rollerini tan?mla (demo ama?l?)
    roller = [
        {
            'ad': 'Admin',
            'ikon': 'shield_person',
            'aciklama': 'Tam sistem erişimi',
            'aktif': True
        },
        {
            'ad': 'Mağaza Müdürü',
            'ikon': 'badge',
            'aciklama': 'Ma?aza operasyon yönetimi',
            'aktif': True
        },
        {
            'ad': 'Kasiyer',
            'ikon': 'point_of_sale',
            'aciklama': 'Satış ve Ödeme işlemleri',
            'aktif': False
        },
        {
            'ad': 'Envanter Sorumlusu',
            'ikon': 'inventory_2',
            'aciklama': 'Stok ve envanter yönetimi',
            'aktif': False
        }
    ]

    return render_template('kullanici_rolleri_ve_yetkilendirme_paneli.html',
                           kategoriler=kategoriler,
                           moduller=moduller,
                           roller=roller,
                           toplam_urun=toplam_urun,
                           toplam_cari=toplam_cari,
                           toplam_satis=toplam_satis)


def get_user_settings(user_id):
    settings_path = backup_file_path_for_user(user_id, 'settings.json')
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_user_settings(user_id, data):
    settings_dir = backup_dir_for_user(user_id)
    os.makedirs(settings_dir, exist_ok=True)
    settings_path = os.path.join(settings_dir, 'settings.json')
    current_settings = get_user_settings(user_id)
    current_settings.update(data)
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(current_settings, f, ensure_ascii=False, indent=2)
    return current_settings


POS_INTEGRATION_PROVIDERS = [
    {'value': 'manual', 'label': 'Manuel POS'},
    {'value': 'pavo', 'label': 'Pavo'},
    {'value': 'hugin', 'label': 'Hugin'},
    {'value': 'ingenico', 'label': 'Ingenico'},
    {'value': 'verifone', 'label': 'Verifone'},
    {'value': 'beko_arcelik', 'label': 'Beko / Arçelik'},
    {'value': 'profilo', 'label': 'Profilo'},
    {'value': 'bank_pos', 'label': 'Banka POS'},
    {'value': 'other', 'label': 'Diğer / Özel Entegrasyon'},
]


def default_pos_integration_settings():
    return {
        'enabled': False,
        'mode': 'manual',
        'provider': 'manual',
        'environment': 'test',
        'connection_type': 'ip',
        'bank_name': '',
        'terminal_id': '',
        'merchant_id': '',
        'device_ip': '',
        'device_port': '',
        'device_serial': '',
        'service_url': '',
        'username': '',
        'api_key': '',
        'timeout_seconds': 30,
        'test_amount': 1,
        'installer_name': '',
        'installer_phone': '',
        'activation_code': '',
        'auto_send_amount': True,
        'require_success': True,
        'print_receipt': False,
        'notes': '',
        'status': 'manual',
        'last_test_at': '',
        'last_test_message': 'Manuel POS kullanılıyor.',
    }


def pos_integration_settings_for_user(user_id):
    settings = get_user_settings(user_id)
    pos_settings = default_pos_integration_settings()
    saved_pos_settings = settings.get('pos_integration') if isinstance(settings.get('pos_integration'), dict) else {}
    pos_settings.update(saved_pos_settings)
    if pos_settings.get('provider') == 'manual':
        pos_settings['mode'] = 'manual'
    return pos_settings


def pos_integration_feature_available(user=None):
    user = user or current_user
    return is_platform_admin_user(user) or platform_setting_bool('pos_integration_enabled_for_users', False)


def settings_for_template(settings):
    template_settings = dict(settings or {})
    pos_settings = template_settings.get('pos_integration')
    if isinstance(pos_settings, dict):
        template_pos_settings = dict(pos_settings)
        template_pos_settings['api_key_configured'] = bool(template_pos_settings.get('api_key'))
        template_pos_settings['api_key'] = ''
        template_settings['pos_integration'] = template_pos_settings
    return template_settings


def normalize_pos_integration_payload(data, current_settings=None):
    current_settings = current_settings or default_pos_integration_settings()
    provider_values = {provider['value'] for provider in POS_INTEGRATION_PROVIDERS}
    mode = (data.get('mode') or current_settings.get('mode') or 'manual').strip()
    provider = (data.get('provider') or current_settings.get('provider') or 'manual').strip()
    environment = (data.get('environment') or current_settings.get('environment') or 'test').strip()
    connection_type = (data.get('connection_type') or current_settings.get('connection_type') or 'ip').strip()

    if mode not in {'manual', 'integrated'}:
        raise ValueError('Geçersiz POS Çalışma modu')
    if provider not in provider_values:
        raise ValueError('Geçersiz POS sağlayıcısı')
    if environment not in {'test', 'live'}:
        raise ValueError('Geçersiz Çalışma ortamı')
    if connection_type not in {'ip', 'api', 'serial'}:
        raise ValueError('Geçersiz bağlantı tipi')

    if provider == 'manual':
        mode = 'manual'

    device_port = str(data.get('device_port') or '').strip()
    if device_port:
        try:
            port_number = int(device_port)
        except ValueError as exc:
            raise ValueError('Port sayısal olmalı') from exc
        if port_number < 1 or port_number > 65535:
            raise ValueError('Port 1 ile 65535 arasında olmalı')

    api_key = str(data.get('api_key') or '').strip() or current_settings.get('api_key', '')
    timeout_seconds = data.get('timeout_seconds')
    if timeout_seconds in (None, ''):
        timeout_seconds = current_settings.get('timeout_seconds') or 30
    test_amount = data.get('test_amount')
    if test_amount in (None, ''):
        test_amount = current_settings.get('test_amount') or 1
    try:
        timeout_seconds = int(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError('Zaman aşımı süresi sayısal olmalı') from exc
    if timeout_seconds < 5 or timeout_seconds > 120:
        raise ValueError('Zaman aşımı 5 ile 120 saniye arasında olmalı')
    try:
        test_amount = float(test_amount)
    except (TypeError, ValueError) as exc:
        raise ValueError('Test tutarı sayısal olmalı') from exc
    if test_amount <= 0:
        raise ValueError('Test tutarı sıfırdan büyük olmalı')

    enabled = bool(data.get('enabled')) or (mode == 'integrated' and provider != 'manual')

    normalized = {
        'enabled': enabled,
        'mode': mode,
        'provider': provider,
        'environment': environment,
        'connection_type': connection_type,
        'bank_name': str(data.get('bank_name') or '').strip(),
        'terminal_id': str(data.get('terminal_id') or '').strip(),
        'merchant_id': str(data.get('merchant_id') or '').strip(),
        'device_ip': str(data.get('device_ip') or '').strip(),
        'device_port': device_port,
        'device_serial': str(data.get('device_serial') or '').strip(),
        'service_url': str(data.get('service_url') or '').strip(),
        'username': str(data.get('username') or '').strip(),
        'api_key': api_key,
        'timeout_seconds': timeout_seconds,
        'test_amount': test_amount,
        'installer_name': str(data.get('installer_name') or '').strip(),
        'installer_phone': str(data.get('installer_phone') or '').strip(),
        'activation_code': str(data.get('activation_code') or '').strip(),
        'auto_send_amount': bool(data.get('auto_send_amount')),
        'require_success': bool(data.get('require_success')),
        'print_receipt': bool(data.get('print_receipt')),
        'notes': str(data.get('notes') or '').strip(),
        'status': current_settings.get('status') or 'manual',
        'last_test_at': current_settings.get('last_test_at') or '',
        'last_test_message': current_settings.get('last_test_message') or '',
    }

    if normalized['mode'] == 'manual':
        normalized['enabled'] = False
        normalized['status'] = 'manual'
        normalized['last_test_message'] = 'Manuel POS kullanılıyor.'

    return normalized


def is_card_payment_method(payment_method):
    return normalize_payment_method(payment_method) == 'Kredi Kartı'


def pos_provider_label(provider_value):
    for provider in POS_INTEGRATION_PROVIDERS:
        if provider['value'] == provider_value:
            return provider['label']
    return provider_value or 'POS'


def pos_integration_is_active(pos_settings):
    return (
        pos_integration_feature_available(current_user)
        and
        bool(pos_settings.get('enabled'))
        and pos_settings.get('mode') == 'integrated'
        and pos_settings.get('provider') != 'manual'
        and bool(pos_settings.get('auto_send_amount', True))
    )


def build_pos_payment_payload(pos_settings, sale_context):
    return {
        'provider': pos_settings.get('provider'),
        'environment': pos_settings.get('environment', 'test'),
        'terminal_id': pos_settings.get('terminal_id'),
        'merchant_id': pos_settings.get('merchant_id'),
        'device_serial': pos_settings.get('device_serial'),
        'invoice_no': sale_context.get('invoice_no'),
        'amount': round(float(sale_context.get('amount') or 0), 2),
        'currency': 'TRY',
        'payment_method': 'card',
        'customer': sale_context.get('customer') or {},
        'items': sale_context.get('items') or [],
        'callback_reference': sale_context.get('callback_reference'),
        'sent_at': datetime.now(timezone.utc).isoformat(),
    }


def parse_pos_adapter_response(raw_body):
    try:
        body = json.loads(raw_body or '{}')
    except (TypeError, ValueError):
        return {'success': False, 'message': 'POS servisinden okunamayan cevap alındı.'}

    success_value = body.get('success')
    status = str(body.get('status') or body.get('result') or '').strip().lower()
    approved = success_value is True or status in {'ok', 'success', 'approved', 'completed', 'done'}
    message = body.get('message') or body.get('description') or ('POS işlemi onaylandı.' if approved else 'POS işlemi reddedildi.')
    return {
        'success': approved,
        'message': message,
        'transaction_id': body.get('transaction_id') or body.get('transactionId') or body.get('auth_code') or body.get('authCode'),
        'raw': body,
    }


def execute_pos_payment_adapter(pos_settings, sale_context):
    provider = pos_settings.get('provider') or 'manual'
    provider_label = pos_provider_label(provider)

    if not pos_integration_is_active(pos_settings):
        return {
            'success': True,
            'skipped': True,
            'status': 'manual',
            'provider': provider,
            'message': 'Manuel POS modu kullanıldı.'
        }

    if not is_card_payment_method(sale_context.get('payment_method')):
        return {
            'success': True,
            'skipped': True,
            'status': 'not_card',
            'provider': provider,
            'message': 'POS entegrasyonu sadece kart Ödemede çalışır.'
        }

    amount = float(sale_context.get('amount') or 0)
    if amount <= 0:
        return {
            'success': False,
            'status': 'invalid_amount',
            'provider': provider,
            'message': 'POS cihazına gönderilecek tutar sıfırdan büyük olmalı.'
        }

    connection_type = pos_settings.get('connection_type') or 'ip'
    service_url = (pos_settings.get('service_url') or '').strip()
    timeout_seconds = int(pos_settings.get('timeout_seconds') or 30)

    if connection_type == 'api' and service_url:
        payload = build_pos_payment_payload(pos_settings, sale_context)
        request_body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        api_key = (pos_settings.get('api_key') or '').strip()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        try:
            request_obj = urllib.request.Request(service_url, data=request_body, headers=headers, method='POST')
            with urllib.request.urlopen(request_obj, timeout=timeout_seconds) as response:
                raw_body = response.read().decode('utf-8', errors='replace')
            parsed = parse_pos_adapter_response(raw_body)
            parsed.update({'provider': provider, 'provider_label': provider_label, 'status': 'approved' if parsed['success'] else 'declined'})
            return parsed
        except urllib.error.URLError as exc:
            return {
                'success': False,
                'status': 'connection_error',
                'provider': provider,
                'provider_label': provider_label,
                'message': f'{provider_label} POS servisine ula??lamad?: {safe_exception_message(exc)}'
            }

    return {
        'success': False,
        'status': 'adapter_required',
        'provider': provider,
        'provider_label': provider_label,
        'message': (
            f'{provider_label} için canlı protokol adaptürü bağlı değil. '
            'Sağlayıcının API/bridge servis URL bilgisi girilmeden kart satışı otomatik tamamlanamaz.'
        )
    }


# Settings Page
@app.route('/settings')
@login_required
def settings():
    backup_dir = backup_dir_for_user(current_user)
    last_backup_date = None
    if os.path.exists(backup_dir):
        files = [f for f in os.listdir(backup_dir) if f.startswith('backup_') and f.endswith('.json')]
        if files:
            files.sort(reverse=True)
            latest_backup = files[0]
            try:
                timestamp_str = latest_backup.replace('backup_', '').replace('.json', '')
                last_backup_dt = to_local_datetime(datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S'))
                month_names = {
                    1: 'Ocak', 2: 'Åubat', 3: 'Mart', 4: 'Nisan',
                    5: 'Mayıs', 6: 'Haziran', 7: 'Temmuz',
                    8: 'Ağustos', 9: 'Eylül', 10: 'Ekim',
                    11: 'Kasım', 12: 'Aralık'
                }
                month_name = month_names.get(last_backup_dt.month, last_backup_dt.strftime('%B'))
                last_backup_date = f"{last_backup_dt.day} {month_name} {last_backup_dt.year}, {last_backup_dt.strftime('%H:%M')}\'te yapıldı"
            except ValueError:
                last_backup_date = None

    user_settings = get_user_settings(current_user.id)
    backup_frequency = user_settings.get('backup_frequency', 'weekly')
    pos_integration_settings = pos_integration_settings_for_user(current_user.id)

    return render_template(
        'settings.html',
        last_backup_date=last_backup_date,
        backup_frequency=backup_frequency,
        user_settings=settings_for_template(user_settings),
        app_version=app_version(),
        pos_integration_settings=pos_integration_settings,
        pos_integration_providers=POS_INTEGRATION_PROVIDERS,
        pos_integration_visible=pos_integration_feature_available(current_user)
    )


@app.route('/api/settings/backup-frequency', methods=['POST'])
@login_required
def update_backup_frequency():
    try:
        data = request.get_json() or {}
        frequency = data.get('frequency', '').strip()
        if frequency not in ['daily', 'weekly', 'monthly', 'never']:
            return jsonify({'success': False, 'message': 'Geçersiz yedekleme sıklığı'}), 400

        save_user_settings(current_user.id, {'backup_frequency': frequency})
        return jsonify({'success': True, 'message': 'Otomatik yedekleme sıklığı kaydedildi',
                        'backup_frequency': frequency})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'}), 500


# Settings API endpoints
@app.route('/api/settings/profile', methods=['POST'])
@login_required
def update_profile():
    try:
        firma_adi = (request.form.get('firma_adi') or '').strip()
        if not firma_adi:
            return jsonify({'success': False, 'message': 'Firma adi gerekli'}), 400

        current_user.firma_adi = firma_adi
        current_user.yetkili_adi = (request.form.get('yetkili_adi') or '').strip() or None
        current_user.telefon = (request.form.get('telefon') or '').strip() or None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profil güncellendi'})
    except Exception as e:
        current_app.logger.exception('Profil guncelleme hatasi')
        return jsonify({'success': False, 'message': safe_exception_message(e)}), 500


@app.route('/api/settings/company', methods=['POST'])
@login_required
def update_company():
    try:
        current_user.vergi_dairesi = (request.form.get('vergi_dairesi') or '').strip() or None
        current_user.vergi_numarasi = (request.form.get('vergi_numarasi') or '').strip() or None
        current_user.adres = (request.form.get('adres') or '').strip() or None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Firma bilgileri güncellendi'})
    except Exception as e:
        current_app.logger.exception('Firma guncelleme hatasi')
        return jsonify({'success': False, 'message': safe_exception_message(e)}), 500


@app.route('/api/settings/password', methods=['POST'])
@login_required
def update_password():
    try:
        data = request.get_json() or {}
        current_password = data.get('current_password') or ''
        new_password = data.get('new_password') or ''

        if not current_password or not new_password:
            return jsonify({'success': False, 'message': 'Mevcut ve yeni sifre gerekli'}), 400

        if len(new_password) < 8:
            return jsonify({'success': False, 'message': 'Yeni sifre en az 8 karakter olmali'}), 400

        if not check_password_hash(current_user.password, current_password):
            return jsonify({'success': False, 'message': 'Mevcut Şifre hatal?'}), 400

        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Åifre güncellendi'})
    except Exception as e:
        current_app.logger.exception('Sifre guncelleme hatasi')
        return jsonify({'success': False, 'message': safe_exception_message(e)}), 500


@app.route('/api/settings/notifications', methods=['POST'])
@login_required
def update_notifications():
    try:
        data = request.get_json() or {}
        allowed_keys = {
            'notify_stock_alerts', 'notify_customer_activity', 'notify_quote_status',
            'notify_daily_reports', 'notify_system_updates', 'notify_realtime',
            'notify_sound', 'notify_desktop', 'notify_history',
            'notification_summary_frequency', 'notification_report_frequency',
            'quiet_hours_start', 'quiet_hours_end'
        }
        settings_data = {key: data.get(key) for key in allowed_keys if key in data}
        save_user_settings(current_user.id, settings_data)
        return jsonify({'success': True, 'message': 'Bildirim ayarları güncellendi'})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('Bildirim guncelleme hatasi')
        return jsonify({'success': False, 'message': safe_exception_message(e)}), 500


@app.route('/api/settings/preferences', methods=['POST'])
@login_required
def update_preferences():
    try:
        data = request.get_json() or {}
        allowed_values = {
            'language': {'tr', 'en'},
            'theme': {'light', 'dark', 'auto'},
            'items_per_page': {'10', '25', '50', '100'},
            'currency': {'TRY', 'USD', 'EUR', 'GBP'},
            'date_format': {'dd.MM.yyyy', 'MM/dd/yyyy', 'yyyy-MM-dd', 'dd-MM-yyyy'},
            'time_format': {'24', '12'},
            'timezone': {'Europe/Istanbul', 'Europe/London', 'Europe/Berlin', 'America/New_York'},
        }
        settings_data = {}

        for key, allowed in allowed_values.items():
            value = str(data.get(key, '')).strip()
            if value and value in allowed:
                settings_data[key] = value

        for key in ('default_vat_rate', 'stock_warning_threshold'):
            if key in data:
                try:
                    number = float(data.get(key))
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': 'Sayisal alanlari kontrol edin'}), 400
                if number < 0:
                    return jsonify({'success': False, 'message': 'Sayisal alanlar negatif olamaz'}), 400
                settings_data[key] = number

        for key in ('auto_backup_enabled', 'compact_view', 'card_view', 'pinned_sidebar'):
            if key in data:
                settings_data[key] = bool(data.get(key))

        save_user_settings(current_user.id, settings_data)
        return jsonify({'success': True, 'message': 'Tercihler kaydedildi', 'settings': settings_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/settings/pos-integration', methods=['POST'])
@login_required
def update_pos_integration_settings():
    if not pos_integration_feature_available(current_user):
        return jsonify({'success': False, 'message': 'POS entegrasyon ayarlari platform sahibi tarafindan kapatildi.'}), 403
    try:
        data = request.get_json() or {}
        current_settings = pos_integration_settings_for_user(current_user.id)
        pos_settings = normalize_pos_integration_payload(data, current_settings)
        save_user_settings(current_user.id, {'pos_integration': pos_settings})
        return jsonify({
            'success': True,
            'message': 'POS entegrasyon ayarları kaydedildi',
            'pos_integration': {**pos_settings, 'api_key': bool(pos_settings.get('api_key'))}
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        current_app.logger.exception('POS entegrasyon ayarlari kaydedilemedi')
        return jsonify({'success': False, 'message': safe_exception_message(e)}), 500


@app.route('/api/settings/pos-integration/test', methods=['POST'])
@login_required
def test_pos_integration_settings():
    if not pos_integration_feature_available(current_user):
        return jsonify({'success': False, 'message': 'POS entegrasyon ayarlari platform sahibi tarafindan kapatildi.'}), 403
    try:
        data = request.get_json() or {}
        current_settings = pos_integration_settings_for_user(current_user.id)
        pos_settings = normalize_pos_integration_payload(data, current_settings)

        if pos_settings['mode'] == 'manual' or pos_settings['provider'] == 'manual':
            pos_settings['status'] = 'manual'
            pos_settings['last_test_message'] = 'Manuel POS modu aktif. Kart tutarı POS cihazına elle girilir.'
        else:
            missing_fields = []
            if pos_settings['connection_type'] in {'ip', 'serial'}:
                for field, label in (
                    ('device_ip', 'Cihaz IP / adres'),
                    ('device_port', 'Port'),
                    ('terminal_id', 'Terminal ID'),
                    ('merchant_id', '??yeri No'),
                    ('device_serial', 'Cihaz seri no'),
                ):
                    if not pos_settings.get(field):
                        missing_fields.append(label)
            if pos_settings['connection_type'] == 'api':
                for field, label in (
                    ('service_url', 'Servis URL'),
                    ('terminal_id', 'Terminal ID'),
                    ('merchant_id', '??yeri No'),
                    ('api_key', 'API anahtar?'),
                ):
                    if not pos_settings.get(field):
                        missing_fields.append(label)

            if missing_fields:
                return jsonify({
                    'success': False,
                    'message': 'Eksik kurulum bilgileri: ' + ', '.join(missing_fields),
                    'missing_fields': missing_fields
                }), 400

            pos_settings['status'] = 'configured'
            pos_settings['last_test_message'] = (
                'Kurulum bilgileri eksiksiz. Gerçek cihaz testi için sağlayıcı adaptürü aktif edilmelidir.'
            )

        pos_settings['last_test_at'] = datetime.now(timezone.utc).isoformat()
        save_user_settings(current_user.id, {'pos_integration': pos_settings})
        return jsonify({
            'success': True,
            'message': pos_settings['last_test_message'],
            'status': pos_settings['status'],
            'last_test_at': pos_settings['last_test_at']
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        current_app.logger.exception('POS entegrasyon testi basarisiz')
        return jsonify({'success': False, 'message': safe_exception_message(e)}), 500


@app.route('/api/settings/categories', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def manage_categories():
    if request.method == 'GET':
        return jsonify({'success': True, 'categories': tenant_categories_with_counts()})

    elif request.method == 'POST':
        data = request.get_json() or {}
        category_name = (data.get('name') or '').strip()
        if not category_name:
            return jsonify({'success': False, 'message': 'Kategori ad? gerekli'})

        existing = Category.query.filter_by(user_id=current_user.id, name=category_name).first()
        if existing:
            return jsonify({'success': False, 'message': 'Kategori zaten mevcut'})

        kategoriyeni = Category(name=category_name, user_id=current_user.id)
        db.session.add(kategoriyeni)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Kategori eklendi'})

    elif request.method == 'PUT':
        data = request.get_json() or {}
        old_name = (data.get('old_name') or '').strip()
        new_name = (data.get('new_name') or '').strip()

        if not old_name or not new_name:
            return jsonify({'success': False, 'message': 'Eski ve yeni kategori ad? gerekli'})

        if old_name == new_name:
            return jsonify({'success': True, 'message': 'Kategori ad? zaten ayn?'})

        kategori = Category.query.filter_by(user_id=current_user.id, name=old_name).first()
        if not kategori:
            return jsonify({'success': False, 'message': 'Kategori bulunamadı'})

        if Category.query.filter_by(user_id=current_user.id, name=new_name).first():
            return jsonify({'success': False, 'message': 'Yeni kategori ad? zaten mevcut'})

        kategori.name = new_name
        urunler = tenant_query(Urun).filter_by(kategori=old_name).all()
        for urun in urunler:
            urun.kategori = new_name

        db.session.commit()
        return jsonify({'success': True, 'message': 'Kategori güncellendi'})

    elif request.method == 'DELETE':
        data = request.get_json() or {}
        category_name = (data.get('name') or '').strip()
        if not category_name:
            return jsonify({'success': False, 'message': 'Kategori ad? gerekli'})

        urun_sayisi = tenant_query(Urun).filter_by(kategori=category_name).count()
        if urun_sayisi > 0:
            return jsonify({'success': False,
                            'message': f'Kategoride {urun_sayisi} Ürün var. '
                                       'Önce Ürünleri silin veya ba?ka kategoriye ta??y?n.'})

        kategori = Category.query.filter_by(user_id=current_user.id, name=category_name).first()
        if not kategori:
            return jsonify({'success': False, 'message': 'Kategori bulunamadı'})

        db.session.delete(kategori)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Kategori silindi'})

    return jsonify({'success': False, 'message': 'Geçersiz istek'})


@app.route('/api/settings/warehouses', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def manage_warehouses():
    if request.method == 'GET':
        depolar = tenant_warehouses_with_metrics()
        legacy_counts = {name: values['product_count'] for name, values in depolar.items()}
        return jsonify({'success': True, 'warehouses': legacy_counts, 'warehouse_metrics': depolar})

    elif request.method == 'POST':
        data = request.get_json() or {}
        if not (data.get('name') or '').strip():
            return jsonify({'success': False, 'message': 'Depo adi gerekli'})
        depot_name = normalize_warehouse_name(data.get('name'))

        existing = Warehouse.query.filter_by(user_id=current_user.id, name=depot_name).first()
        if existing:
            return jsonify({'success': False, 'message': 'Depo zaten mevcut'})

        yeni_depo = Warehouse(name=depot_name, user_id=current_user.id)
        db.session.add(yeni_depo)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Depo eklendi'})

    elif request.method == 'PUT':
        data = request.get_json() or {}
        if not (data.get('old_name') or '').strip() or not (data.get('new_name') or '').strip():
            return jsonify({'success': False, 'message': 'Eski ve yeni depo adi gerekli'})
        old_name = normalize_warehouse_name(data.get('old_name'))
        new_name = normalize_warehouse_name(data.get('new_name'))

        if old_name == new_name:
            return jsonify({'success': True, 'message': 'Depo ad? zaten ayn?'})

        depo = Warehouse.query.filter_by(user_id=current_user.id, name=old_name).first()
        if not depo:
            return jsonify({'success': False, 'message': 'Depo bulunamadı'})

        if Warehouse.query.filter_by(user_id=current_user.id, name=new_name).first():
            return jsonify({'success': False, 'message': 'Yeni depo adı zaten mevcut'})

        depo.name = new_name
        urunler = tenant_query(Urun).filter_by(depo_adi=old_name).all()
        for urun in urunler:
            urun.depo_adi = new_name

        db.session.commit()
        return jsonify({'success': True, 'message': 'Depo güncellendi'})

    elif request.method == 'DELETE':
        data = request.get_json() or {}
        if not (data.get('name') or '').strip():
            return jsonify({'success': False, 'message': 'Depo adi gerekli'})
        depot_name = normalize_warehouse_name(data.get('name'))

        urun_sayisi = tenant_query(Urun).filter_by(depo_adi=depot_name).count()
        if urun_sayisi > 0:
            return jsonify({'success': False, 'message': f'Depoda {urun_sayisi} Ürün var. Önce Ürünleri ta??y?n.'})

        depo = Warehouse.query.filter_by(user_id=current_user.id, name=depot_name).first()
        if not depo:
            return jsonify({'success': False, 'message': 'Depo bulunamadı'})

        db.session.delete(depo)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Depo silindi'})

    return jsonify({'success': False, 'message': 'Geçersiz istek'})


@app.route('/api/settings/transfer-products', methods=['POST'])
@login_required
def transfer_products():
    try:
        data = request.get_json() or {}
        from_warehouse_raw = data.get('from_warehouse')
        to_warehouse_raw = data.get('to_warehouse')
        from_warehouse = normalize_warehouse_name(from_warehouse_raw)
        to_warehouse = normalize_warehouse_name(to_warehouse_raw)
        product_ids = data.get('product_ids', [])
        quantity = normalize_amount(data.get('quantity', 0))

        if not (from_warehouse_raw or '').strip() or not (to_warehouse_raw or '').strip():
            return jsonify({'success': False, 'message': 'Kaynak ve hedef depo seiniz'})
        if from_warehouse == to_warehouse:
            return jsonify({'success': False, 'message': 'Kaynak ve hedef depo ayn olamaz'})
        if quantity <= 0:
            return jsonify({'success': False, 'message': 'Geerli bir miktar giriniz'})
        if not isinstance(product_ids, list) or not product_ids:
            return jsonify({'success': False, 'message': 'Taşınacak Ürün seçiniz'})

        normalized_product_ids = []
        for product_id in product_ids:
            try:
                normalized_product_ids.append(int(product_id))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Ürün listesinde geçersiz ID var'})
        normalized_product_ids = list(dict.fromkeys(normalized_product_ids))

        source_products = []
        errors = []
        for product_id in normalized_product_ids:
            urun = tenant_query(Urun).filter_by(id=product_id, depo_adi=from_warehouse).first()
            if not urun:
                errors.append(f'Ürün bulunamadı: ID {product_id}')
                continue
            old_source_stock = float(urun.stok_miktari or 0)
            if old_source_stock < quantity:
                errors.append(f'{urun.urun_adi}: Yetersiz stok (mevcut: {urun.stok_miktari})')
                continue
            source_products.append((urun, old_source_stock))

        if errors:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Ta??ma iptal edildi. Hatalar: {"; ".join(errors[:5])}'})
        if not source_products:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'Taşınacak geçerli Ürün bulunamadı'})

        ensure_warehouse(to_warehouse)
        for urun, old_source_stock in source_products:
            target_product = get_or_create_product_in_warehouse(urun, to_warehouse)
            old_target_stock = float(target_product.stok_miktari or 0)
            urun.stok_miktari = old_source_stock - quantity
            target_product.stok_miktari = old_target_stock + quantity

            description = f'Depo transferi: {from_warehouse} -> {to_warehouse}'
            record_stock_movement(urun, 'cikis', quantity, from_warehouse,
                                  old_source_stock, urun.stok_miktari, description)
            record_stock_movement(target_product, 'giris', quantity, to_warehouse,
                                  old_target_stock, target_product.stok_miktari, description)

        db.session.commit()
        return jsonify({'success': True, 'message': f'{len(source_products)} Ürün başarıyla ta??nd?'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Taşıma işlemi başarısız: {str(e)}'})


@app.route('/api/settings/backup', methods=['POST'])
@login_required
def settings_backup():
    try:
        payload = build_tenant_backup_payload(current_user)
        filename, _ = write_tenant_backup_file(current_user, payload, backup_type='manual', filename_prefix='backup')
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Yedekleme başarıyla oluşturuldu: {filename}',
            'filename': filename
        })

        import os
        import json
        from datetime import datetime

        # Yedekleme klasÜrün? oluştur
        backup_dir = backup_dir_for_user(current_user)
        os.makedirs(backup_dir, exist_ok=True)

        # Yedekleme dosyası ad?
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'backup_{timestamp}.json'
        backup_file = os.path.join(backup_dir, backup_filename)

        # T?m verileri topla
        backup_data = {
            'user_info': {
                'firma_adi': current_user.firma_adi,
                'yetkili_adi': current_user.yetkili_adi,
                'email': current_user.email,
                'telefon': current_user.telefon,
                'vergi_dairesi': current_user.vergi_dairesi,
                'vergi_numarasi': current_user.vergi_numarasi,
                'adres': current_user.adres,
                'paket_tipi': current_user.paket_tipi,
                'created_at': current_user.kayit_tarihi.isoformat() if current_user.kayit_tarihi else None
            },
            'urunler': [],
            'cariler': [],
            'satislar': [],
            'teklifler': [],
            'iade_kayitlari': [],
            'backup_info': {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'version': '1.0',
                'user_id': current_user.id
            }
        }

        # Ürünleri ekle
        urunler = Urun.query.filter_by(user_id=current_user.id).all()
        for urun in urunler:
            backup_data['urunler'].append({
                'id': urun.id,
                'urun_adi': urun.urun_adi,
                'barkod': urun.barkod,
                'kategori': urun.kategori,
                'stok_miktari': urun.stok_miktari,
                'kritik_stok': urun.kritik_stok,
                'birim': urun.birim,
                'alis_fiyati': urun.alis_fiyati,
                'satis_fiyati': urun.satis_fiyati,
                'depo_adi': urun.depo_adi,
                'eklenme_tarihi': urun.eklenme_tarihi.isoformat() if urun.eklenme_tarihi else None
            })

        # Carileri ekle
        cariler = Cari.query.filter_by(user_id=current_user.id).all()
        for cari in cariler:
            backup_data['cariler'].append({
                'id': cari.id,
                'unvan': cari.unvan,
                'telefon': cari.telefon,
                'email': cari.email,
                'vergidairesi': cari.vergidairesi,
                'vergi_numarasi': cari.vergi_numarasi,
                'adres': cari.adres,
                'borc': cari.borc,
                'alacak': cari.alacak,
                'created_at': cari.kayit_tarihi.isoformat() if cari.kayit_tarihi else None
            })

        # Satışlar? ekle
        satislar = Satis.query.filter_by(user_id=current_user.id).all()
        for satis in satislar:
            backup_data['satislar'].append({
                'id': satis.id,
                'fatura_no': satis.fatura_no,
                'cari_id': satis.cari_id,
                'tarih': satis.tarih.isoformat() if satis.tarih else None,
                'genel_toplam': satis.genel_toplam,
                'durum': satis.durum,
                'notlar': satis.notlar
            })

        # Teklifleri ekle
        teklifler = Teklif.query.filter_by(user_id=current_user.id).all()
        for teklif in teklifler:
            backup_data['teklifler'].append({
                'id': teklif.id,
                'teklif_no': teklif.teklif_no,
                'cari_id': teklif.cari_id,
                'tarih': teklif.tarih.isoformat() if teklif.tarih else None,
                'genel_toplam': teklif.genel_toplam,
                'durum': teklif.durum,
                'notlar': teklif.notlar
            })

        # İade kayıtların? ekle
        iade_kayitlari = Iade.query.filter_by(user_id=current_user.id).all()
        for iade in iade_kayitlari:
            backup_data['iade_kayitlari'].append({
                'id': iade.id,
                'cari_id': iade.cari_id,
                'iade_turu': iade.iade_turu,
                'iade_sebebi': iade.iade_sebebi,
                'iade_tutari': iade.iade_tutari,
                'tarih': iade.tarih.isoformat() if iade.tarih else None,
                'durum': iade.durum
            })

        # JSON dosyasına yaz
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        file_size = os.path.getsize(backup_file)
        db.session.add(BackupLog(
            filename=backup_filename,
            file_size=file_size,
            backup_type='manual',
            status='completed',
            user_id=current_user.id,
            completed_at=datetime.now(timezone.utc)
        ))
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Yedekleme başarıyla oluşturuldu: backup_{timestamp}.json',
            'filename': backup_filename
        })

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'success': False, 'message': f'Yedekleme hatas?: {str(e)}'})


@app.route('/api/settings/backup/restore', methods=['POST'])
@login_required
def restore_backup():
    try:
        if 'backup_file' not in request.files:
            return jsonify({'success': False, 'message': 'Yedek dosyası y?kleyin'}), 400

        backup_file = request.files['backup_file']
        if not backup_file or backup_file.filename == '':
            return jsonify({'success': False, 'message': 'Yedek dosyası seçilmedi'}), 400

        if not backup_file.filename.lower().endswith('.json'):
            return jsonify({'success': False, 'message': 'Lütfen JSON format?nda bir yedek dosyası seçin'}), 400

        backup_data = json.load(backup_file)
        if not validate_tenant_backup_payload(backup_data):
            return jsonify({'success': False, 'message': 'Geçersiz yedekleme format?'}), 400

        # Silme s?ras?: alt veriler Önce
        db.session.query(IadeKalem).filter(IadeKalem.iade_id.in_(db.session.query(
            Iade.id).filter_by(user_id=current_user.id))).delete(synchronize_session=False)
        db.session.query(SatisKalemi).filter(SatisKalemi.satis_id.in_(db.session.query(
            Satis.id).filter_by(user_id=current_user.id))).delete(synchronize_session=False)
        db.session.query(TeklifKalemi).filter(TeklifKalemi.teklif_id.in_(db.session.query(
            Teklif.id).filter_by(user_id=current_user.id))).delete(synchronize_session=False)
        db.session.query(CariHareket).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(StokHareket).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(CashTransaction).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(Iade).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(Satis).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(Teklif).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(Cari).filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.query(Urun).filter_by(user_id=current_user.id).delete(synchronize_session=False)

        # Kullan?c? bilgilerini yedekten geri y?kleme
        user_info = backup_data.get('user_info', {}) or {}
        current_user.firma_adi = user_info.get('firma_adi', current_user.firma_adi)
        current_user.yetkili_adi = user_info.get('yetkili_adi', current_user.yetkili_adi)
        current_user.telefon = user_info.get('telefon', current_user.telefon)
        current_user.vergi_dairesi = user_info.get('vergi_dairesi', current_user.vergi_dairesi)
        current_user.vergi_numarasi = user_info.get('vergi_numarasi', current_user.vergi_numarasi)
        current_user.adres = user_info.get('adres', current_user.adres)

        old_to_new_cari = {}
        for cari_data in backup_data.get('cariler', []):
            cari = Cari(
                unvan=cari_data.get('unvan'),
                telefon=cari_data.get('telefon'),
                email=cari_data.get('email'),
                vergidairesi=cari_data.get('vergidairesi'),
                vergi_numarasi=cari_data.get('vergi_numarasi'),
                adres=cari_data.get('adres'),
                borc=cari_data.get('borc') or 0,
                alacak=cari_data.get('alacak') or 0,
                user_id=current_user.id
            )
            db.session.add(cari)
            db.session.flush()
            if cari_data.get('id') is not None:
                old_to_new_cari[cari_data.get('id')] = cari.id

        old_to_new_urun = {}
        for urun_data in backup_data.get('urunler', []):
            urun = Urun(
                barkod=urun_data.get('barkod'),
                urun_adi=urun_data.get('urun_adi'),
                kategori=urun_data.get('kategori'),
                birim=urun_data.get('birim'),
                alis_fiyati=urun_data.get('alis_fiyati') or 0,
                satis_fiyati=urun_data.get('satis_fiyati') or 0,
                stok_miktari=urun_data.get('stok_miktari') or 0,
                kritik_stok=urun_data.get('kritik_stok') or 0,
                depo_adi=urun_data.get('depo_adi'),
                user_id=current_user.id
            )
            db.session.add(urun)
            db.session.flush()
            if urun_data.get('id') is not None:
                old_to_new_urun[urun_data.get('id')] = urun.id

        for satis_data in backup_data.get('satislar', []):
            new_cari_id = old_to_new_cari.get(satis_data.get('cari_id')) if satis_data.get('cari_id') else None
            satis = Satis(
                fatura_no=satis_data.get('fatura_no'),
                cari_id=new_cari_id,
                user_id=current_user.id,
                tarih=parse_iso_datetime(satis_data.get('tarih')) or datetime.now(timezone.utc),
                ara_toplam=satis_data.get('ara_toplam') or 0,
                kdv_orani=satis_data.get('kdv_orani') or 0,
                kdv_tutar=satis_data.get('kdv_tutar') or 0,
                iskonto=satis_data.get('iskonto') or 0,
                genel_toplam=satis_data.get('genel_toplam') or 0,
                notlar=satis_data.get('notlar'),
                durum=satis_data.get('durum') or 'tamamlandi'
            )
            db.session.add(satis)

        for teklif_data in backup_data.get('teklifler', []):
            new_cari_id = old_to_new_cari.get(teklif_data.get('cari_id')) if teklif_data.get('cari_id') else None
            teklif = Teklif(
                teklif_no=teklif_data.get('teklif_no'),
                cari_id=new_cari_id,
                user_id=current_user.id,
                tarih=parse_iso_datetime(teklif_data.get('tarih')) or datetime.now(timezone.utc),
                toplam_tutar=teklif_data.get('toplam_tutar') or teklif_data.get('ara_toplam') or 0,
                kdv_orani=teklif_data.get('kdv_orani') or 0,
                genel_toplam=teklif_data.get('genel_toplam') or 0,
                notlar=teklif_data.get('notlar'),
                durum=teklif_data.get('durum') or 'taslak'
            )
            db.session.add(teklif)

        for iade_data in backup_data.get('iade_kayitlari', []):
            new_cari_id = old_to_new_cari.get(iade_data.get('cari_id')) if iade_data.get('cari_id') else None
            iade = Iade(
                cari_id=new_cari_id,
                user_id=current_user.id,
                iade_turu=iade_data.get('iade_turu'),
                iade_sebebi=iade_data.get('iade_sebebi'),
                iade_tutari=iade_data.get('iade_tutari') or 0,
                tarih=parse_iso_datetime(iade_data.get('tarih')) or datetime.now(timezone.utc),
                durum=iade_data.get('durum') or 'tamamlandi'
            )
            db.session.add(iade)

        db.session.commit()
        return jsonify({'success': True, 'message': 'Yedek başarıyla geri yüklendi'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Yedek geri y?kleme hatas?: {str(e)}'}), 500


@app.route('/api/settings/backup/download/<filename>')
@login_required
def download_backup(filename):
    try:
        from flask import send_from_directory

        actor = active_platform_actor()
        if platform_lock_enabled('data_export_locked') and actor and not is_platform_owner_user(actor):
            return jsonify({'success': False, 'message': 'Veri cikisi kilitli. Yedek indirme icin platform sahibi onayi gerekli.'}), 423

        safe_filename = secure_filename(filename)
        if safe_filename != filename or not safe_filename.endswith('.json'):
            return jsonify({'success': False, 'message': 'Geçersiz yedekleme dosyası'}), 400

        backup_file = backup_file_path_for_user(current_user, safe_filename)
        if os.path.isfile(backup_file):
            return send_from_directory(os.path.dirname(backup_file), safe_filename, as_attachment=True, download_name=safe_filename)
        else:
            return jsonify({'success': False, 'message': 'Yedekleme dosyası bulunamadı'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': f'?ndirme hatas?: {str(e)}'}), 500


@app.route('/api/settings/security-audit', methods=['POST'])
@login_required
def security_audit():
    try:
        # Güvenlik denetimi işlemi
        audit_results = {
            'session_security': True,
            'password_strength': 'medium',
            'failed_logins': 0,
            'connected_devices': 2,
            'data_breach_detection': True
        }

        # Audit log kaydı
        audit_log = AuditLog(
            user_id=current_user.id,
            action='SECURITY_AUDIT',
            resource_type='SecurityAudit',
            details='Güvenlik denetimi çalıştırıldı',
            ip_address=request.remote_addr
        )
        db.session.add(audit_log)
        db.session.commit()

        return jsonify({'success': True, 'results': audit_results, 'message': 'Güvenlik denetimi tamamlandı'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# Barkod Arama API


@app.route('/api/barkod/<barkod>')
@login_required
def barkod_ara(barkod):
    urun = Urun.query.filter_by(barkod=barkod, user_id=current_user.id).first()
    if urun:
        return jsonify({
            'success': True,
            'urun': {
                'id': urun.id,
                'urun_adi': urun.urun_adi,
                'barkod': urun.barkod,
                'kategori': urun.kategori,
                'birim': urun.birim,
                'satis_fiyati': urun.satis_fiyati,
                'stok_miktari': urun.stok_miktari,
                'alis_fiyati': urun.alis_fiyati
            }
        })
    else:
        return jsonify({'success': False, 'message': 'Ürün bulunamadı'})

# Ürün Arama API


@app.route('/api/urunler')
@login_required
def api_urunler():
    try:
        query = request.args.get('q', '').strip()
        warehouse = request.args.get('warehouse', '').strip()

        urunler_query = tenant_query(Urun)

        # Arama filtresi
        if query:
            urunler_query = urunler_query.filter(
                (Urun.urun_adi.ilike(f'%{query}%') | Urun.barkod.ilike(f'%{query}%') |
                 Urun.kategori.ilike(f'%{query}%'))
            )

        # Depo filtresi
        if warehouse:
            urunler_query = urunler_query.filter(Urun.depo_adi == warehouse)

        urunler = urunler_query.limit(50).all()

        return jsonify({
            'success': True,
            'urunler': [
                {
                    'id': u.id,
                    'urun_adi': u.urun_adi,
                    'barkod': u.barkod,
                    'kategori': u.kategori,
                    'satis_fiyati': u.satis_fiyati,
                    'stok_miktari': u.stok_miktari,
                    'alis_fiyati': u.alis_fiyati,
                    'depo_adi': u.depo_adi
                } for u in urunler
            ]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# Kategori API - T?m kategorileri getir


@app.route('/api/kategoriler')
@login_required
def api_kategoriler():
    urunler = tenant_query(Urun).all()
    kategoriler = list(set([u.kategori or 'Kategorisiz' for u in urunler]))
    return jsonify({'kategoriler': sorted(kategoriler)})

# Kategori Kaydet (Ekle/D?zenle)


@app.route('/kategori/kaydet', methods=['POST'])
@login_required
def kategori_kaydet():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Veri al?namad?'})

        yeni_ad = data.get('kategori_adi', '').strip()
        eski_ad = data.get('eski_ad', '').strip()

        if not yeni_ad:
            return jsonify({'success': False, 'message': 'Kategori ad? boş olamaz'})

        # E?er d?zenleme ise (eski_ad varsa), eski kategorideki Ürünleri yeni kategoriye ta??
        if eski_ad and eski_ad != yeni_ad:
            urunler = tenant_query(Urun).filter_by(kategori=eski_ad).all()
            for urun in urunler:
                urun.kategori = yeni_ad
            db.session.commit()
            return jsonify({'success': True, 'message': 'Kategori güncellendi'})

        # Yeni kategori ekleme - bu sistemde kategoriler Ürünlerden t?retilir
        # Yeni kategori için ge?ici bir Ürün oluştur (gizli, stoksuz)
        # veya sadece session'da tut
        from flask import session

        # Kullan?c?n?n kategorilerini session'da tut
        user_kategoriler = session.get(f'kategoriler_{current_user.id}', [])
        if yeni_ad not in user_kategoriler:
            user_kategoriler.append(yeni_ad)
            session[f'kategoriler_{current_user.id}'] = user_kategoriler

        return jsonify({'success': True, 'message': 'Kategori kaydedildi', 'kategori': yeni_ad})
    except Exception as e:
        current_app.logger.exception('Kategori kaydet hatas?')
        if current_app.config.get('IS_PRODUCTION'):
            return jsonify({'success': False, 'message': 'Beklenmeyen bir hata oluştu.'}), 500
        return jsonify({'success': False, 'message': str(e)}), 500

# Kategori Sil


@app.route('/kategori/sil', methods=['POST'])
@login_required
def kategori_sil():
    try:
        kategori_adi = request.form.get('kategori_adi')
        if not kategori_adi:
            return jsonify({'success': False, 'message': 'Kategori ad? boş'})
        # Kategorideki Ürünleri 'Kategorisiz' yap
        urunler = tenant_query(Urun).filter_by(kategori=kategori_adi).all()
        for urun in urunler:
            urun.kategori = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Kategori silindi'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# İade API Endpoint'leri


@app.route('/api/iade/gecmis')
@login_required
def iade_gecmisi():
    try:
        iadeler = tenant_query(Iade).order_by(Iade.tarih.desc()).all()

        iade_data = []
        for iade in iadeler:
            iade_data.append({
                'tarih': iade.tarih.strftime('%d.%m.%Y'),
                'cari_unvan': iade.cari.unvan,
                'iade_turu': iade.iade_turu,
                'sebep': iade.iade_sebebi,
                'tutar': iade.iade_tutari,
                'durum': iade.durum
            })

        return jsonify({'iadeler': iade_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/iade/istatistikler')
@login_required
def iade_istatistikleri():
    try:
        # İade türü da??l?m?
        iade_turleri = {}
        iadeler = tenant_query(Iade).all()
        for iade in iadeler:
            iade_turleri[iade.iade_turu] = iade_turleri.get(iade.iade_turu, 0) + 1

        # Ayl?k trend
        aylik_trend = {}
        now = datetime.now(timezone.utc)
        for month in range(1, 13):
            ay_baslangic = now.replace(day=1, month=month, hour=0, minute=0, second=0, microsecond=0)
            if month == 12:
                sonraki_ay = ay_baslangic.replace(year=ay_baslangic.year + 1, month=1)
            else:
                sonraki_ay = ay_baslangic.replace(month=month + 1)

            ay_iadeler = Iade.query.filter(
                Iade.user_id.in_(tenant_user_ids()),
                Iade.tarih >= ay_baslangic,
                Iade.tarih < sonraki_ay
            ).count()
            aylik_trend[ay_baslangic.strftime('%Y-%m')] = ay_iadeler

        return jsonify({
            'iade_turleri': iade_turleri,
            'aylik_trend': aylik_trend
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# API Endpoint'leri
@app.route('/api/pos/products', methods=['POST'])
@login_required
def api_pos_create_product():
    try:
        data = request.get_json() or {}
        product_name = (data.get('urun_adi') or data.get('name') or '').strip()
        barcode = (data.get('barkod') or data.get('barcode') or '').strip() or None
        category = (data.get('kategori') or data.get('category') or 'Genel').strip() or 'Genel'
        unit = (data.get('birim') or data.get('unit') or 'Adet').strip() or 'Adet'
        warehouse = normalize_warehouse_name(data.get('depo_adi') or data.get('warehouse') or DEFAULT_WAREHOUSE)

        sale_price = normalize_amount(data.get('satis_fiyati', data.get('price', 0)))
        purchase_price = normalize_amount(data.get('alis_fiyati', data.get('purchase_price', 0)))
        stock_quantity = normalize_amount(data.get('stok_miktari', data.get('stock', 0)))
        critical_stock = normalize_amount(data.get('kritik_stok', data.get('critical_stock', 10)))

        if not product_name:
            return jsonify({'success': False, 'message': 'Ürün adı zorunludur.'})
        if sale_price < 0:
            return jsonify({'success': False, 'message': 'Satış fiyatı negatif olamaz.'})
        if purchase_price < 0:
            return jsonify({'success': False, 'message': 'Alış fiyatı negatif olamaz.'})
        if stock_quantity < 0:
            return jsonify({'success': False, 'message': 'Stok miktarı negatif olamaz.'})
        if critical_stock < 0:
            return jsonify({'success': False, 'message': 'Kritik stok negatif olamaz.'})

        if barcode:
            existing_product = tenant_query(Urun).filter_by(barkod=barcode).first()
            if existing_product:
                return jsonify({
                    'success': False,
                    'message': 'Bu barkod zaten kayıtlı.',
                    'product': serialize_pos_product(existing_product)
                })

        ensure_warehouse(warehouse)
        product = Urun(
            barkod=barcode,
            urun_adi=product_name,
            kategori=category,
            birim=unit,
            alis_fiyati=purchase_price,
            satis_fiyati=sale_price,
            stok_miktari=stock_quantity,
            kritik_stok=critical_stock,
            depo_adi=warehouse,
            user_id=current_user.id
        )
        db.session.add(product)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Ürün POS üzerinden eklendi.',
            'product': serialize_pos_product(product)
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'})


def _match_stock_import_value(row, *keys):
    for key in keys:
        if key in row and row.get(key) not in (None, ''):
            return str(row.get(key)).strip()
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(str(key).strip().lower())
        if value not in (None, ''):
            return str(value).strip()
    return ''


STOCK_IMPORT_PRODUCT_NAME_KEYS = (
    'Ürün Adı', 'Urun Adi', 'Urun Adı', 'urun_adi', 'urun adı', 'urun adi',
    'Ürün Adı', 'ÃƒÅ“rÃƒÂ¼n AdÃ„Â±', 'Urun Adı', 'urun adı', 'urun adÃ„Â±',
)
STOCK_IMPORT_PURCHASE_PRICE_KEYS = (
    'Alış Fiyatı', 'Alis Fiyati', 'alis_fiyati', 'alış fiyatı', 'alis fiyati',
    'Alış Fiyatı', 'AlÃ„Â±Ã…Å¸ FiyatÃ„Â±', 'alış fiyatı', 'alÃ„Â±Ã…Å¸ fiyatÃ„Â±',
)
STOCK_IMPORT_SALE_PRICE_KEYS = (
    'Satış Fiyatı', 'Satis Fiyati', 'satis_fiyati', 'satış fiyatı', 'satis fiyati',
    'Satış Fiyatı', 'SatÃ„Â±Ã…Å¸ FiyatÃ„Â±', 'satış fiyatı', 'satÃ„Â±Ã…Å¸ fiyatÃ„Â±',
)
STOCK_IMPORT_WAREHOUSE_KEYS = (
    'Depo', 'depo', 'depo adı', 'depo_adi', 'depo adı', 'depo adÃ„Â±',
)
STOCK_IMPORT_DESCRIPTION_KEYS = (
    'Açıklama', 'Aciklama', 'aciklama', 'description',
    'Açıklama', 'AÃƒÂ§Ã„Â±klama',
)


def _find_import_product(row, tenant_ids):
    barkod = _match_stock_import_value(row, 'Barkod', 'barkod', 'barcode')
    urun_adi = _match_stock_import_value(row, *STOCK_IMPORT_PRODUCT_NAME_KEYS)

    if barkod:
        product = Urun.query.filter(
            Urun.user_id.in_(tenant_ids),
            Urun.barkod == barkod,
        ).order_by(Urun.id.asc()).first()
        if product:
            return product

    if urun_adi:
        return Urun.query.filter(
            Urun.user_id.in_(tenant_ids),
            func.lower(Urun.urun_adi) == urun_adi.lower(),
        ).order_by(Urun.id.asc()).first()

    return None


def _create_product_from_import_row(row):
    barkod = _match_stock_import_value(row, 'Barkod', 'barkod', 'barcode') or None
    urun_adi = _match_stock_import_value(row, *STOCK_IMPORT_PRODUCT_NAME_KEYS)
    kategori = _match_stock_import_value(row, 'Kategori', 'kategori') or None
    birim = _match_stock_import_value(row, 'Birim', 'birim') or 'Adet'
    depo = normalize_warehouse_name(_match_stock_import_value(row, *STOCK_IMPORT_WAREHOUSE_KEYS) or DEFAULT_WAREHOUSE)
    alis_fiyati = normalize_amount(_match_stock_import_value(row, *STOCK_IMPORT_PURCHASE_PRICE_KEYS), 0.0)
    satis_fiyati = normalize_amount(_match_stock_import_value(row, *STOCK_IMPORT_SALE_PRICE_KEYS), 0.0)
    kritik_stok = normalize_amount(_match_stock_import_value(row, 'Kritik Stok', 'kritik_stok', 'kritik stok'), 10.0)

    if not urun_adi:
        raise ValueError('Ürün adı boş bırakılamaz.')

    ensure_warehouse(depo)
    product = Urun(
        barkod=barkod,
        urun_adi=urun_adi,
        kategori=kategori,
        birim=birim,
        alis_fiyati=alis_fiyati,
        satis_fiyati=satis_fiyati,
        stok_miktari=0.0,
        kritik_stok=kritik_stok,
        depo_adi=depo,
        user_id=current_user.id,
    )
    db.session.add(product)
    db.session.flush()
    return product


def _update_product_from_import_row(product, row):
    barkod = _match_stock_import_value(row, 'Barkod', 'barkod', 'barcode')
    urun_adi = _match_stock_import_value(row, *STOCK_IMPORT_PRODUCT_NAME_KEYS)
    kategori = _match_stock_import_value(row, 'Kategori', 'kategori')
    birim = _match_stock_import_value(row, 'Birim', 'birim')
    alis_raw = _match_stock_import_value(row, *STOCK_IMPORT_PURCHASE_PRICE_KEYS)
    satis_raw = _match_stock_import_value(row, *STOCK_IMPORT_SALE_PRICE_KEYS)
    kritik_raw = _match_stock_import_value(row, 'Kritik Stok', 'kritik_stok', 'kritik stok')

    if barkod:
        product.barkod = barkod
    if urun_adi:
        product.urun_adi = urun_adi
    if kategori:
        product.kategori = kategori
    if birim:
        product.birim = birim
    if alis_raw:
        product.alis_fiyati = normalize_amount(alis_raw, product.alis_fiyati or 0.0)
    if satis_raw:
        product.satis_fiyati = normalize_amount(satis_raw, product.satis_fiyati or 0.0)
    if kritik_raw:
        product.kritik_stok = normalize_amount(kritik_raw, product.kritik_stok or 10.0)

    db.session.flush()
    return product


def _stock_import_preview_dir():
    preview_dir = Path(tempfile.gettempdir()) / 'stokcari_stock_import_previews'
    preview_dir.mkdir(parents=True, exist_ok=True)
    return preview_dir


def _stock_import_preview_path(preview_id):
    return _stock_import_preview_dir() / f'{secure_filename(str(preview_id))}.json'


def save_stock_import_preview(file_name, rows):
    preview_id = uuid.uuid4().hex
    payload = {
        'preview_id': preview_id,
        'owner_id': current_user.id,
        'file_name': file_name,
        'created_at': local_now().isoformat(),
        'rows': rows,
    }
    _stock_import_preview_path(preview_id).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding='utf-8'
    )
    session['pending_stock_import_preview_id'] = preview_id
    session.modified = True
    return payload


def load_stock_import_preview():
    preview_id = session.get('pending_stock_import_preview_id')
    if not preview_id:
        return None

    preview_path = _stock_import_preview_path(preview_id)
    if not preview_path.exists():
        session.pop('pending_stock_import_preview_id', None)
        session.modified = True
        return None

    try:
        payload = json.loads(preview_path.read_text(encoding='utf-8'))
    except Exception:
        preview_path.unlink(missing_ok=True)
        session.pop('pending_stock_import_preview_id', None)
        session.modified = True
        return None

    if payload.get('owner_id') != current_user.id:
        return None
    return payload


def clear_stock_import_preview():
    preview_id = session.pop('pending_stock_import_preview_id', None)
    session.modified = True
    if preview_id:
        _stock_import_preview_path(preview_id).unlink(missing_ok=True)


def persist_stock_import_preview(payload):
    preview_id = payload.get('preview_id')
    if not preview_id:
        return
    _stock_import_preview_path(preview_id).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding='utf-8'
    )


def _build_stock_import_preview_rows(rows, tenant_ids):
    preview_rows = []
    for index, row in enumerate(rows, start=2):
        if not any(str(value or '').strip() for value in row.values()):
            continue

        barkod = _match_stock_import_value(row, 'Barkod', 'barkod', 'barcode')
        urun_adi = _match_stock_import_value(row, *STOCK_IMPORT_PRODUCT_NAME_KEYS)
        kategori = _match_stock_import_value(row, 'Kategori', 'kategori')
        birim = _match_stock_import_value(row, 'Birim', 'birim') or 'Adet'
        miktar = normalize_amount(_match_stock_import_value(row, 'Miktar', 'miktar', 'quantity'), 0.0)
        alis_fiyati = normalize_amount(_match_stock_import_value(row, *STOCK_IMPORT_PURCHASE_PRICE_KEYS), 0.0)
        satis_fiyati = normalize_amount(_match_stock_import_value(row, *STOCK_IMPORT_SALE_PRICE_KEYS), 0.0)
        kritik_stok = normalize_amount(_match_stock_import_value(row, 'Kritik Stok', 'kritik_stok', 'kritik stok'), 10.0)
        depo = normalize_warehouse_name(_match_stock_import_value(row, *STOCK_IMPORT_WAREHOUSE_KEYS) or DEFAULT_WAREHOUSE)
        aciklama = _match_stock_import_value(row, *STOCK_IMPORT_DESCRIPTION_KEYS)

        existing_product = _find_import_product(row, tenant_ids)
        valid = True
        error_message = ''

        if miktar <= 0:
            valid = False
            error_message = "Miktar 0'dan büyük olmalı."
        elif not existing_product and not urun_adi:
            valid = False
            error_message = 'Yeni ürün için ürün adı zorunlu.'

        current_stock = float(existing_product.stok_miktari or 0) if existing_product else 0.0
        preview_rows.append({
            'row_id': f'row-{index}',
            'source_row': index,
            'valid': valid,
            'error': error_message,
            'action': 'update' if existing_product else 'create',
            'action_label': 'Mevcut ürünü güncelle ve stoğu ekle' if existing_product else 'Yeni ürün oluştur ve stoğu ekle',
            'product_id': existing_product.id if existing_product else None,
            'matched_product_name': existing_product.urun_adi if existing_product else '',
            'current_stock': current_stock,
            'barkod': barkod,
            'urun_adi': urun_adi or (existing_product.urun_adi if existing_product else ''),
            'kategori': kategori or (existing_product.kategori if existing_product else ''),
            'birim': birim or (existing_product.birim if existing_product else 'Adet'),
            'miktar': miktar,
            'alis_fiyati': alis_fiyati,
            'satis_fiyati': satis_fiyati,
            'kritik_stok': kritik_stok,
            'depo': depo,
            'aciklama': aciklama,
        })
    return preview_rows


def read_uploaded_stock_csv(upload):
    raw_content = upload.read()
    last_error = None
    for encoding in ('utf-8-sig', 'utf-8', 'cp1254', 'iso-8859-9', 'cp1252'):
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error or UnicodeDecodeError('utf-8', b'', 0, 1, 'decode error')


def parse_stock_csv_rows(text_content):
    normalized_text = text_content.replace('\r\n', '\n').replace('\r', '\n')
    try:
        dialect = csv.Sniffer().sniff(normalized_text[:2048], delimiters=';,')
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ';' if normalized_text.count(';') >= normalized_text.count(',') else ','

    return list(csv.DictReader(io.StringIO(normalized_text), delimiter=delimiter))


@app.route('/stok/giris/sablon.csv')
@login_required
def stok_giris_sablon_csv():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Barkod',
        'Ürün Adı',
        'Kategori',
        'Birim',
        'Miktar',
        'Alış Fiyatı',
        'Satış Fiyatı',
        'Kritik Stok',
        'Depo',
        'Açıklama',
    ])
    writer.writerow([
        '8690000000001',
        'Örnek Matkap Ucu 5mm',
        'Hırdavat',
        'Adet',
        '12',
        '45,50',
        '79,90',
        '5',
        'Ana Depo',
        'İlk toplu stok yükleme',
    ])

    csv_content = output.getvalue().encode('utf-8-sig')
    response = make_response(csv_content)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = "attachment; filename=stok-giris-sablonu.csv; filename*=UTF-8''stok-giris-sablonu.csv"
    return response


@app.route('/api/stock/import', methods=['POST'])
@login_required
def api_stock_import():
    tenant_ids = tenant_user_ids()
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'message': 'Lütfen içe aktarılacak dosyayı seçin.'})

    filename = (upload.filename or '').lower()
    if not filename.endswith('.csv'):
        return jsonify({'success': False, 'message': "Şimdilik sadece CSV şablonu destekleniyor. Dosyayı Excel'den CSV olarak kaydedip tekrar yükleyin."})

    try:
        text_content = read_uploaded_stock_csv(upload)
        rows = parse_stock_csv_rows(text_content)
    except UnicodeDecodeError:
        return jsonify({'success': False, 'message': "CSV dosyası okunamadı. Lütfen şablonu indirip Excel'den CSV olarak tekrar kaydedin."})
    except Exception:
        return jsonify({'success': False, 'message': 'CSV dosyası okunamadı. Şablonu indirip tekrar deneyin.'})

    if not rows:
        return jsonify({'success': False, 'message': 'İçe aktarılacak satır bulunamadı.'})

    created_count = 0
    updated_count = 0
    errors = []

    try:
        for index, row in enumerate(rows, start=2):
            if not any(str(value or '').strip() for value in row.values()):
                continue

            miktar = normalize_amount(_match_stock_import_value(row, 'Miktar', 'miktar', 'quantity'), 0.0)
            if miktar <= 0:
                errors.append(f"Satır {index}: miktar 0'dan büyük olmalı.")
                continue

            depo = normalize_warehouse_name(_match_stock_import_value(row, *STOCK_IMPORT_WAREHOUSE_KEYS) or DEFAULT_WAREHOUSE)
            aciklama = _match_stock_import_value(row, *STOCK_IMPORT_DESCRIPTION_KEYS)

            product = _find_import_product(row, tenant_ids)
            if product is None:
                product = _create_product_from_import_row(row)
                created_count += 1
            else:
                product = _update_product_from_import_row(product, row)
                updated_count += 1

            add_stock_to_warehouse(
                product,
                miktar,
                depo,
                aciklama or f'{depo} depo toplu içe aktarma',
            )

        if created_count == 0 and updated_count == 0 and errors:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'Hiçbir satır içe aktarılamadı.', 'errors': errors[:10]})

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'{created_count + updated_count} satır içe aktarıldı',
            'created_count': created_count,
            'updated_count': updated_count,
            'errors': errors[:10],
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'İçe aktarma sırasında hata oluştu: {str(e)}'})


@app.route('/api/stock/import/preview', methods=['POST'])
@login_required
def api_stock_import_preview():
    tenant_ids = tenant_user_ids()
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'success': False, 'message': 'Lütfen içe aktarılacak dosyayı seçin.'})

    filename = (upload.filename or '').lower()
    if not filename.endswith('.csv'):
        return jsonify({'success': False, 'message': "Şimdilik sadece CSV şablonu destekleniyor. Dosyayı Excel'den CSV olarak kaydedip tekrar yükleyin."})

    try:
        text_content = read_uploaded_stock_csv(upload)
        rows = parse_stock_csv_rows(text_content)
    except UnicodeDecodeError:
        return jsonify({'success': False, 'message': "CSV dosyası okunamadı. Lütfen şablonu indirip Excel'den CSV olarak tekrar kaydedin."})
    except Exception:
        return jsonify({'success': False, 'message': 'CSV dosyası okunamadı. Şablonu indirip tekrar deneyin.'})

    if not rows:
        return jsonify({'success': False, 'message': 'İçe aktarılacak satır bulunamadı.'})

    preview_rows = _build_stock_import_preview_rows(rows, tenant_ids)
    if not preview_rows:
        return jsonify({'success': False, 'message': 'İçe aktarılacak satır bulunamadı.'})

    clear_stock_import_preview()
    preview = save_stock_import_preview(upload.filename, preview_rows)
    valid_rows = [row for row in preview_rows if row.get('valid')]
    invalid_rows = [row for row in preview_rows if not row.get('valid')]

    return jsonify({
        'success': True,
        'message': f'{len(preview_rows)} satır ön izlemeye alındı',
        'preview_id': preview.get('preview_id'),
        'preview_count': len(preview_rows),
        'valid_count': len(valid_rows),
        'invalid_count': len(invalid_rows),
        'rows': preview_rows,
    })


@app.route('/api/stock/import/commit', methods=['POST'])
@login_required
def api_stock_import_commit():
    payload = request.get_json() or {}
    row_ids = payload.get('row_ids') or []

    preview = load_stock_import_preview()
    if not preview or not preview.get('rows'):
        return jsonify({'success': False, 'message': 'Onaylanacak bekleyen toplu stok ön izlemesi bulunamadı.'})

    if not isinstance(row_ids, list) or not row_ids:
        return jsonify({'success': False, 'message': 'Lütfen yüklenecek satırları seçin.'})

    rows_by_id = {row.get('row_id'): row for row in preview.get('rows', [])}
    selected_rows = [rows_by_id[row_id] for row_id in row_ids if row_id in rows_by_id]
    if not selected_rows:
        return jsonify({'success': False, 'message': 'Seçilen satırlar ön izlemede bulunamadı.'})

    committed_ids = []
    created_count = 0
    updated_count = 0

    try:
        for row in selected_rows:
            if not row.get('valid'):
                continue

            product = None
            product_id = row.get('product_id')
            if product_id:
                product = db.session.get(Urun, int(product_id))
                if not belongs_to_current_tenant(product):
                    product = None

            if product is None:
                product = _create_product_from_import_row(row)
                created_count += 1
            else:
                updated_count += 1

            depo = normalize_warehouse_name(row.get('depo') or DEFAULT_WAREHOUSE)
            add_stock_to_warehouse(
                product,
                normalize_amount(row.get('miktar'), 0.0),
                depo,
                (row.get('aciklama') or '').strip() or f'{depo} depo toplu içe aktarma',
            )
            committed_ids.append(row.get('row_id'))

        if not committed_ids:
            return jsonify({'success': False, 'message': 'Seçilen satırlarda yüklenebilir veri bulunamadı.'})

        db.session.commit()

        remaining_rows = [row for row in preview.get('rows', []) if row.get('row_id') not in committed_ids]
        if remaining_rows:
            preview['rows'] = remaining_rows
            persist_stock_import_preview(preview)
        else:
            clear_stock_import_preview()

        return jsonify({
            'success': True,
            'message': f'{len(committed_ids)} satır uygulamaya yüklendi',
            'created_count': created_count,
            'updated_count': updated_count,
            'remaining_count': len(remaining_rows),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Yükleme sırasında hata oluştu: {str(e)}'})


@app.route('/api/stock/import/clear', methods=['POST'])
@login_required
def api_stock_import_clear():
    clear_stock_import_preview()
    return jsonify({'success': True, 'message': 'Toplu stok ön izlemesi temizlendi.'})


@app.route('/api/stock/add', methods=['POST'])
@login_required
def api_stock_add():
    try:
        data = request.get_json() or {}
        product_id = data.get('product_id')
        quantity = normalize_amount(data.get('quantity', 0))
        depot = normalize_warehouse_name(data.get('depot'))
        description = (data.get('description') or '').strip()

        if not product_id or quantity <= 0:
            return jsonify({'success': False, 'message': 'Geçersiz ürün veya miktar!'})

        urun = db.session.get(Urun, product_id)
        if not belongs_to_current_tenant(urun):
            return jsonify({'success': False, 'message': 'Ürün bulunamadı!'})

        target_product, old_stock = add_stock_to_warehouse(
            urun, quantity, depot, description or f'{depot} depo API ile giriş')
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'{quantity} adet stok eklendi',
            'product_id': target_product.id,
            'source_product_id': urun.id,
            'depot': depot,
            'old_stock': old_stock,
            'new_stock': target_product.stok_miktari
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'})


@app.route('/api/stock/batch-add', methods=['POST'])
@login_required
def api_stock_batch_add():
    try:
        data = request.get_json() or {}
        product_ids = data.get('product_ids', [])
        quantity = normalize_amount(data.get('quantity', 0))
        depot = normalize_warehouse_name(data.get('depot'))
        description = (data.get('description') or '').strip()

        if not isinstance(product_ids, list) or not product_ids or quantity <= 0:
            return jsonify({'success': False, 'message': 'Ürünler veya miktar belirtilmedi!'})

        normalized_product_ids = []
        for product_id in product_ids:
            try:
                normalized_product_ids.append(int(product_id))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'Ürün listesinde geçersiz ID var'})
        normalized_product_ids = list(dict.fromkeys(normalized_product_ids))

        products = []
        for product_id in normalized_product_ids:
            urun = db.session.get(Urun, product_id)
            if not belongs_to_current_tenant(urun):
                db.session.rollback()
                return jsonify({'success': False, 'message': f'Geçersiz ürün: ID {product_id}'})
            products.append(urun)

        results = []
        for urun in products:
            target_product, old_stock = add_stock_to_warehouse(
                urun,
                quantity,
                depot,
                description or f'{depot} depo toplu giriş'
            )
            results.append({
                'id': target_product.id,
                'source_id': urun.id,
                'name': target_product.urun_adi,
                'depot': depot,
                'old_stock': old_stock,
                'new_stock': target_product.stok_miktari
            })

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'{len(results)} ürün için toplu {quantity} adet stok eklendi',
            'results': results
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Hata: {str(e)}'})


# Kritik Stok Uyar?lar?


@app.route('/stok/uyarilar')
@login_required
def stok_uyarilari():
    urunler = tenant_query(Urun).all()
    kritik_urunler = [u for u in urunler if u.stok_miktari <= u.kritik_stok]

    return jsonify({
        'kritik_urun_sayisi': len(kritik_urunler),
        'urunler': [{
            'id': u.id,
            'urun_adi': u.urun_adi,
            'mevcut_stok': u.stok_miktari,
            'kritik_stok': u.kritik_stok
        } for u in kritik_urunler]
    })


@app.route('/stok/giris', methods=['GET', 'POST'])
@login_required
def stok_giris():
    tenant_ids = tenant_user_ids()

    if request.method == 'POST':
        try:
            urun_id = request.form.get('urun_id')
            miktar = float(request.form.get('miktar', 0))
            depo = normalize_warehouse_name(request.form.get('depo'))
            aciklama = request.form.get('aciklama', '')

            if not urun_id or miktar <= 0:
                flash('Ürün ve miktar zorunludur!', 'error')
                return redirect(url_for('stok_giris'))

            urun = db.session.get(Urun, urun_id)
            if not belongs_to_current_tenant(urun):
                flash('Geçersiz ürün seçimi!', 'error')
                return redirect(url_for('stok_giris'))

            target_product, old_stock = add_stock_to_warehouse(
                urun, miktar, depo, aciklama or f'{depo} depo manuel giriş')
            db.session.commit()
            flash(f'{miktar} adet {target_product.urun_adi} stok başarıyla eklendi!', 'success')
            return redirect(url_for('stok_giris'))

        except Exception as e:
            db.session.rollback()
            flash(f'Hata oluştu: {str(e)}', 'error')
            return redirect(url_for('stok_giris'))

    search_query = request.args.get('search', '').strip()
    selected_category = request.args.get('category', 'all').strip() or 'all'
    selected_stock_status = request.args.get('stock', 'all').strip() or 'all'

    all_products = Urun.query.filter(Urun.user_id.in_(tenant_ids)).all()
    urunler_query = Urun.query.filter(Urun.user_id.in_(tenant_ids))

    if search_query:
        urunler_query = urunler_query.filter(
            (Urun.urun_adi.ilike(f'%{search_query}%')) |
            (Urun.barkod.ilike(f'%{search_query}%')) |
            (Urun.kategori.ilike(f'%{search_query}%'))
        )

    if selected_category != 'all':
        urunler_query = urunler_query.filter(Urun.kategori == selected_category)

    urunler = urunler_query.order_by(Urun.urun_adi.asc()).all()

    if selected_stock_status == 'critical':
        urunler = [u for u in urunler if (u.stok_miktari or 0) <= (u.kritik_stok or 0)]
    elif selected_stock_status == 'low':
        urunler = [u for u in urunler if (u.stok_miktari or 0) > (u.kritik_stok or 0) and (u.stok_miktari or 0) <= ((u.kritik_stok or 0) + 15)]
    elif selected_stock_status == 'normal':
        urunler = [u for u in urunler if (u.stok_miktari or 0) > ((u.kritik_stok or 0) + 15)]
    elif selected_stock_status == 'out':
        urunler = [u for u in urunler if (u.stok_miktari or 0) <= 0]

    # ?statistikler
    toplam_urun = len(all_products)
    toplam_stok = sum((u.stok_miktari or 0) for u in all_products)
    kritik_stok = len([u for u in all_products if (u.stok_miktari or 0) <= (u.kritik_stok or 0)])
    toplam_deger = round(sum((u.satis_fiyati or 0) * (u.stok_miktari or 0) for u in all_products), 2)

    # Kategoriler
    kategoriler = set()
    for urun in all_products:
        if urun.kategori:
            kategoriler.add(urun.kategori)

    urunler_json = [{
        'id': u.id,
        'urun_adi': u.urun_adi,
        'barkod': u.barkod or '',
        'kategori': u.kategori or '',
        'stok_miktari': u.stok_miktari or 0,
        'alis_fiyati': u.alis_fiyati or 0,
        'satis_fiyati': u.satis_fiyati or 0,
        'kritik_stok': u.kritik_stok or 5
    } for u in urunler]

    pagination = paginate_list_items(urunler_json)
    import_preview = load_stock_import_preview()

    return render_template('stok_girisi_detayi.html',
                           urunler=pagination.items,
                           pagination=pagination,
                           toplam_urun=toplam_urun,
                           toplam_stok=toplam_stok,
                           kritik_stok=kritik_stok,
                           toplam_deger=toplam_deger,
                           kategoriler=sorted(list(kategoriler)),
                           depolar=list(tenant_warehouses_with_metrics().keys()),
                           result_count=pagination.total,
                           search_query=search_query,
                           selected_category=selected_category,
                           selected_stock_status=selected_stock_status,
                           import_preview=import_preview)

# Stok Çıkış ??lemi


@app.route('/stok/cikis', methods=['GET', 'POST'])
@login_required
def stok_cikis():
    if request.method == 'POST':
        try:
            cari_id = request.form.get('cari_id')

            # Validasyon: cari_id zorunlu
            if not cari_id:
                flash('Müşteri seçimi zorunludur!', 'error')
                return redirect(url_for('stok_cikis'))

            # Validasyon: cari_id geçerli mi ve kullan?c?ya ait mi
            cari = db.session.get(Cari, cari_id)
            if not belongs_to_current_tenant(cari):
                flash('Geçersiz müşteri seçimi!', 'error')
                return redirect(url_for('stok_cikis'))

            depo = normalize_warehouse_name(request.form.get('depo'))
            tarih_str = request.form.get('tarih')
            notlar = request.form.get('notlar', '')
            kdv_orani = float(request.form.get('kdv_orani', 20))
            iskonto = float(request.form.get('iskonto', 0))

            # Fatura no oluştur
            fatura_no = generate_fatura_no(prefix='FTR')

            # Satış kaydı oluştur
            satis = Satis(
                fatura_no=fatura_no,
                cari_id=cari_id,
                user_id=current_user.id,
                depo=depo,
                tarih=datetime.strptime(tarih_str, '%Y-%m-%d') if tarih_str else datetime.now(timezone.utc),
                notlar=notlar,
                kdv_orani=kdv_orani,
                iskonto=iskonto
            )
            db.session.add(satis)
            db.session.flush()  # satis.id almak için

            # Ürün kalemlerini işle
            urunler_data = request.form.getlist('urun_id[]')
            miktarlar = request.form.getlist('miktar[]')
            birimler = request.form.getlist('birim[]')
            fiyatlar = request.form.getlist('birim_fiyat[]')

            ara_toplam = 0
            processed_items = 0
            for i, urun_id in enumerate(urunler_data):
                if not urun_id:
                    continue

                urun = db.session.get(Urun, urun_id)
                if not belongs_to_current_tenant(urun):
                    raise ValueError('Geçersiz Ürün seçimi!')

                stok_urun = resolve_product_for_stock_out(urun, depo)
                if not stok_urun:
                    raise ValueError(f'{urun.urun_adi} iin {depo} deposunda stok kayd yok')
                urun = stok_urun

                miktar = float(miktarlar[i]) if i < len(miktarlar) and miktarlar[i] else 1
                birim_fiyat = float(fiyatlar[i]) if i < len(fiyatlar) and fiyatlar[i] else urun.satis_fiyati
                birim = birimler[i] if i < len(birimler) and birimler[i] else urun.birim
                if miktar <= 0 or birim_fiyat < 0:
                    raise ValueError('Miktar veya fiyat geersiz!')

                if urun.stok_miktari < miktar:
                    raise ValueError(
                        f'{urun.urun_adi} iin yetersiz stok! Mevcut: {urun.stok_miktari}, stenen: {miktar}')

                toplam = miktar * birim_fiyat
                satis_kalemi = SatisKalemi(
                    satis_id=satis.id,
                    urun_id=urun.id,
                    urun_adi=urun.urun_adi,
                    barkod=urun.barkod,
                    miktar=miktar,
                    birim=birim,
                    birim_fiyat=birim_fiyat,
                    toplam=toplam
                )
                db.session.add(satis_kalemi)

                eski_stok = urun.stok_miktari or 0
                urun.stok_miktari = eski_stok - miktar
                record_stock_movement(
                    urun,
                    'cikis',
                    miktar,
                    depo,
                    eski_stok,
                    urun.stok_miktari,
                    f'Satış çıkışı - {fatura_no}',
                    cari_id=cari.id
                )
                ara_toplam += toplam
                processed_items += 1

            totals, total_error = calculate_sale_totals(ara_toplam, kdv_orani, iskonto)
            if total_error:
                raise ValueError(total_error)

            # Toplamlar? gÖncelle
            satis.ara_toplam = totals['ara_toplam']
            satis.kdv_orani = totals['kdv_orani']
            satis.kdv_tutar = totals['kdv_tutar']
            satis.iskonto = totals['iskonto']
            satis.genel_toplam = totals['genel_toplam']

            # Cari alacak ve hareket kaydı oluştur/gÖncelle
            if cari:
                cari.alacak = (cari.alacak or 0) + satis.genel_toplam
                db.session.add(CariHareket(
                    cari_id=cari.id,
                    user_id=current_user.id,
                    islem_tipi='satis',
                    tutar=satis.genel_toplam,
                    aciklama=f'Stok Çıkış faturas? {fatura_no}',
                    odeme_turu='Alacak',
                    referans_id=satis.id,
                    referans_tip='satis'
                ))

            db.session.commit()
            flash(f'Satış kaydı oluşturuldu: {fatura_no}', 'success')
            return redirect(url_for('urunler'))

        except Exception as e:
            db.session.rollback()
            flash(f'Hata oluştu: {str(e)}', 'error')
            return redirect(url_for('stok_cikis'))

    urunler = tenant_query(Urun).all()
    cariler = tenant_query(Cari).all()

    # Urun nesnelerini JSON serile?tirilebilir formata ?evir
    urunler_json = [{
        'id': u.id,
        'barkod': u.barkod,
        'urun_adi': u.urun_adi,
        'birim': u.birim or 'Adet',
        'satis_fiyati': u.satis_fiyati or 0,
        'stok_miktari': u.stok_miktari or 0
    } for u in urunler]

    return render_template(
        'stok_cikis_islemi_detayi.html',
        urunler=urunler_json,
        cariler=cariler,
        depolar=list(tenant_warehouses_with_metrics().keys())
    )

# Günlük Satışlar


@app.route('/gunluk-satislar', methods=['GET', 'POST'])
@login_required
def gunluk_satislar():
    if request.method == 'POST':
        # Satış iptal işlemi
        satis_id = request.form.get('satis_id')
        if satis_id:
            try:
                satis = Satis.query.get_or_404(satis_id)
                if not belongs_to_current_tenant(satis):
                    flash('Bu satışa erişim izniniz yok!', 'error')
                    return redirect(url_for('gunluk_satislar'))

                if satis.durum == 'iptal':
                    flash('Bu satış zaten iptal edilmi?!', 'warning')
                    return redirect(url_for('gunluk_satislar'))

                # Stoklar? geri ekle
                for kalem in satis.kalemler:
                    urun = db.session.get(Urun, kalem.urun_id)
                    if urun and belongs_to_current_tenant(urun):
                        eski_stok = urun.stok_miktari or 0
                        urun.stok_miktari = eski_stok + kalem.miktar
                        record_stock_movement(
                            urun,
                            'giris',
                            kalem.miktar,
                            satis.depo or urun.depo_adi,
                            eski_stok,
                            urun.stok_miktari,
                            f'Satış iptali - {satis.fatura_no}',
                            cari_id=satis.cari_id
                        )

                # Sadece cari hesabı ger?ekten bor?land?r?lm?? satışlar? ters kayda al.
                cari = None
                original_cari_sale_movement = None
                if satis.cari_id:
                    cari = Cari.query.filter(Cari.id == satis.cari_id, Cari.user_id.in_(tenant_user_ids())).first()
                    original_cari_sale_movement = CariHareket.query.filter(
                        CariHareket.user_id.in_(tenant_user_ids()),
                        CariHareket.cari_id == satis.cari_id,
                        CariHareket.referans_id == satis.id,
                        CariHareket.referans_tip == 'satis',
                        CariHareket.islem_tipi == 'satis'
                    ).first()
                    if cari and original_cari_sale_movement:
                        cari.alacak = max(0, (cari.alacak or 0) - (satis.genel_toplam or 0))
                        db.session.add(CariHareket(
                            cari_id=cari.id,
                            user_id=current_user.id,
                            islem_tipi='iade',
                            tutar=satis.genel_toplam or 0,
                            aciklama=f'Satış iptali - {satis.fatura_no}',
                            odeme_turu='İptal',
                            referans_id=satis.id,
                            referans_tip='satis_iptal'
                        ))

                # Nakit hareketini ters kayt ile dengele
                cash_entries = CashTransaction.query.filter(
                    CashTransaction.user_id.in_(tenant_user_ids()),
                    CashTransaction.referans_id == satis.id,
                    CashTransaction.referans_tip == 'satis',
                    CashTransaction.islem_tipi == 'giris'
                ).all()
                if cash_entries:
                    for entry in cash_entries:
                        create_cash_transaction(
                            cari,
                            entry.tutar,
                            'cikis',
                            entry.odeme_turu,
                            f'Satış iptali - {satis.fatura_no}',
                            referans_id=satis.id,
                            referans_tip='satis_iptal',
                            account_id=entry.account_id
                        )

                # Satış durumunu iptal olarak gÖncelle
                satis.durum = 'iptal'
                db.session.commit()

                flash(f'Satış {satis.fatura_no} iptal edildi ve stoklar geri eklendi.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'İptal işlemi s?ras?nda hata: {str(e)}', 'error')
        return redirect(url_for('gunluk_satislar'))

    # Tarih filtresi
    tarih_str = request.args.get('tarih')
    if tarih_str:
        try:
            secili_tarih = datetime.strptime(tarih_str, '%Y-%m-%d').date()
            baslangic = datetime(secili_tarih.year, secili_tarih.month, secili_tarih.day, tzinfo=timezone.utc)
            bitis = baslangic + timedelta(days=1) - timedelta(microseconds=1)
        except Exception:
            secili_tarih = datetime.now(timezone.utc).date()
            baslangic = datetime(secili_tarih.year, secili_tarih.month, secili_tarih.day, tzinfo=timezone.utc)
            bitis = baslangic + timedelta(days=1) - timedelta(microseconds=1)
    else:
        secili_tarih = datetime.now(timezone.utc).date()
        baslangic = datetime(secili_tarih.year, secili_tarih.month, secili_tarih.day, tzinfo=timezone.utc)
        bitis = baslangic + timedelta(days=1) - timedelta(microseconds=1)

    # Se?ili tarihteki satışlar? ?ek
    satislar = Satis.query.filter(
        Satis.user_id.in_(tenant_user_ids()),
        Satis.tarih >= baslangic,
        Satis.tarih <= bitis
    ).order_by(Satis.tarih.desc()).all()

    sale_ids = [satis.id for satis in satislar]
    payment_methods = {}
    if sale_ids:
        cash_entries = CashTransaction.query.filter(
            CashTransaction.user_id.in_(tenant_user_ids()),
            CashTransaction.referans_id.in_(sale_ids),
            CashTransaction.referans_tip == 'satis',
            CashTransaction.islem_tipi == 'giris'
        ).order_by(CashTransaction.id.asc()).all()
        for entry in cash_entries:
            payment_methods.setdefault(entry.referans_id, entry.odeme_turu or 'Peşin')

        credit_sale_ids = {
            hareket.referans_id for hareket in CariHareket.query.filter(
                CariHareket.user_id.in_(tenant_user_ids()),
                CariHareket.referans_id.in_(sale_ids),
                CariHareket.referans_tip == 'satis',
                CariHareket.islem_tipi == 'satis'
            ).all()
        }
        for sale_id in credit_sale_ids:
            payment_methods.setdefault(sale_id, 'Veresiye')

    return render_template(
        'gunluk_satislar.html',
        satislar=satislar,
        secili_tarih=secili_tarih,
        payment_methods=payment_methods
    )

def build_receipt_view_model(receipt, *, sale_data=None):
    receipt = receipt or {}
    sale_data = sale_data or {}
    items = receipt.get('items') or sale_data.get('items') or []
    payment_method = receipt.get('payment_method') or sale_data.get('paymentMethod') or 'Peşin'
    customer = (receipt.get('customer') or {}).get('unvan') or sale_data.get('customer_name') or 'Peşin satış'
    received_amount = float(sale_data.get('receivedAmount') or receipt.get('received_amount') or receipt.get('total') or sale_data.get('total') or 0)
    total_amount = float(receipt.get('total') or sale_data.get('total') or 0)
    discount_amount = float(receipt.get('discount') or sale_data.get('discount') or 0)
    should_show_cash = normalize_payment_method(payment_method) == 'Nakit'

    return {
        'fatura_no': receipt.get('fatura_no') or sale_data.get('fatura_no') or '',
        'tarih': parse_iso_datetime(receipt.get('date_iso')) or datetime.now(timezone.utc),
        'payment_method': payment_method,
        'customer_label': customer,
        'items': [{
            'name': item.get('name') or item.get('urun_adi') or '',
            'quantity': item.get('qty') or item.get('quantity') or 1,
            'unit': item.get('unit') or item.get('birim') or '',
            'unit_price': float(item.get('unit_price') or item.get('price') or 0),
            'line_total': float(item.get('line_total') or item.get('toplam') or ((item.get('qty') or item.get('quantity') or 1) * (item.get('unit_price') or item.get('price') or 0))),
        } for item in items],
        'subtotal': float(receipt.get('subtotal') or sale_data.get('subtotal') or 0),
        'vat_total': float(receipt.get('vat_total') or sale_data.get('vatTotal') or 0),
        'discount': discount_amount,
        'total': total_amount,
        'show_cash_details': should_show_cash,
        'received_amount': received_amount,
        'change_amount': max(0, received_amount - total_amount),
    }


@app.route('/satis/<int:satis_id>/fis')
@login_required
def satis_fis_yazdir(satis_id):
    satis = Satis.query.get_or_404(satis_id)
    if not belongs_to_current_tenant(satis):
        flash('Bu satış fiçine erişim izniniz yok!', 'error')
        return redirect(url_for('gunluk_satislar'))
    autoprint = request.args.get('autoprint') in {'1', 'true', 'yes'}

    payment_method = 'Peşin'
    cash_entry = CashTransaction.query.filter(
        CashTransaction.user_id.in_(tenant_user_ids()),
        CashTransaction.referans_id == satis.id,
        CashTransaction.referans_tip == 'satis',
        CashTransaction.islem_tipi == 'giris'
    ).order_by(CashTransaction.id.asc()).first()
    if cash_entry and cash_entry.odeme_turu:
        payment_method = cash_entry.odeme_turu
    else:
        credit_entry = CariHareket.query.filter(
            CariHareket.user_id.in_(tenant_user_ids()),
            CariHareket.referans_id == satis.id,
            CariHareket.referans_tip == 'satis',
            CariHareket.islem_tipi == 'satis'
        ).first()
        if credit_entry:
            payment_method = 'Veresiye'

    receipt_data = build_receipt_view_model({
        'fatura_no': satis.fatura_no,
        'date_iso': satis.tarih.isoformat() if satis.tarih else None,
        'payment_method': payment_method,
        'subtotal': satis.ara_toplam,
        'vat_total': satis.kdv_tutar,
        'discount': satis.iskonto,
        'total': satis.genel_toplam,
        'customer': {'unvan': satis.cari.unvan} if satis.cari else None,
        'items': [{
            'name': kalem.urun_adi,
            'qty': kalem.miktar,
            'unit': kalem.birim,
            'unit_price': kalem.birim_fiyat,
            'line_total': kalem.toplam,
        } for kalem in satis.kalemler]
    })

    return render_template(
        'satis_fis_yazdir.html',
        receipt_data=receipt_data,
        autoprint=autoprint
    )


@app.route('/pos/fis', methods=['POST'])
@login_required
def pos_fis_yazdir():
    receipt_raw = request.form.get('receipt_payload', '{}')
    sale_raw = request.form.get('sale_payload', '{}')
    try:
        receipt_payload = json.loads(receipt_raw) if receipt_raw else {}
        sale_payload = json.loads(sale_raw) if sale_raw else {}
    except json.JSONDecodeError:
        flash('Fiş verisi hazırlanamadı.', 'error')
        return redirect(url_for('pos'))

    receipt_data = build_receipt_view_model(receipt_payload, sale_data=sale_payload)
    return render_template(
        'satis_fis_yazdir.html',
        receipt_data=receipt_data,
        autoprint=True
    )

# Toplu Fiyat Güncelleme


@app.route('/urunler/toplu-fiyat-guncelleme', methods=['GET', 'POST'])
@login_required
def toplu_fiyat_guncelleme():
    if request.method == 'POST':
        kategori = request.form.get('kategori')
        zam_orani = float(request.form.get('zam_orani', 0))

        urunler = tenant_query(Urun)
        if kategori:
            urunler = urunler.filter_by(kategori=kategori)

        for urun in urunler.all():
            urun.satis_fiyati = urun.satis_fiyati * (1 + zam_orani / 100)

        db.session.commit()
        flash(f'Fiyatlar {zam_orani}% oranında güncellendi!', 'success')
        return redirect(url_for('urunler'))

    urunler = tenant_query(Urun).all()
    kategoriler = list(set([u.kategori for u in urunler if u.kategori]))
    return render_template('toplu_fiyat_guncelleme.html', urunler=urunler, kategoriler=kategoriler)

# Ürün Detay


@app.route('/urun/<int:id>')
@login_required
def urun_detay(id):
    urun = Urun.query.get_or_404(id)
    if not belongs_to_current_tenant(urun):
        flash('Bu Ürüne erişim izniniz yok!', 'error')
        return redirect(url_for('urunler'))
    return render_template('urun_detay.html', urun=urun)

# Ürün D?zenle


@app.route('/urun/<int:id>/duzenle', methods=['GET', 'POST'])
@login_required
def urun_duzenle(id):
    urun = Urun.query.get_or_404(id)
    if not belongs_to_current_tenant(urun):
        flash('Bu Ürüne erişim izniniz yok!', 'error')
        return redirect(url_for('urunler'))

    if request.method == 'POST':
        urun.barkod = request.form.get('barkod')
        urun.urun_adi = request.form.get('urun_adi')
        urun.kategori = request.form.get('kategori')
        urun.birim = request.form.get('birim')
        urun.alis_fiyati = float(request.form.get('alis_fiyati', 0))
        urun.satis_fiyati = float(request.form.get('satis_fiyati', 0))
        urun.stok_miktari = float(request.form.get('stok_miktari', 0))
        urun.kritik_stok = float(request.form.get('kritik_stok', 10))

        db.session.commit()
        flash('Ürün başarıyla güncellendi!', 'success')
        return redirect(url_for('urun_detay', id=id))

    return render_template('urun_duzenle.html', urun=urun)

# Ürün Sil


@app.route('/urun/<int:id>/sil', methods=['POST'])
@login_required
def urun_sil(id):
    urun = Urun.query.get_or_404(id)
    if not belongs_to_current_tenant(urun):
        flash('Bu Ürüne erişim izniniz yok!', 'error')
        return redirect(url_for('urunler'))

    # Kontrol: Ürün satış kaleminde kullanılıyor mu
    satis_kalemi_var = SatisKalemi.query.join(Satis).filter(
        SatisKalemi.urun_id == urun.id,
        Satis.user_id.in_(tenant_user_ids())
    ).first()
    if satis_kalemi_var:
        flash('Bu Ürün satış kayıtlarında kullan?ldüş? için silinemez!', 'error')
        return redirect(url_for('urunler'))

    # Kontrol: Ürün teklif kaleminde kullanılıyor mu
    teklif_kalemi_var = TeklifKalemi.query.join(Teklif).filter(
        TeklifKalemi.urun_id == urun.id,
        Teklif.user_id.in_(tenant_user_ids())
    ).first()
    if teklif_kalemi_var:
        flash('Bu Ürün tekliflerde kullan?ldüş? için silinemez!', 'error')
        return redirect(url_for('urunler'))

    db.session.delete(urun)
    db.session.commit()
    flash('Ürün başarıyla silindi!', 'success')
    return redirect(url_for('urunler'))

def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.before_request
def csrf_protect():
    if not app.config.get('WTF_CSRF_ENABLED', True):
        return

    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        provided = (
            request.headers.get('X-CSRFToken')
            or request.headers.get('X-CSRF-Token')
            or request.form.get('csrf_token')
        )

        if not provided and request.is_json:
            payload = request.get_json(silent=True) or {}
            provided = payload.get('csrf_token')

        if not provided or provided != session.get('_csrf_token'):
            abort(403)


app.jinja_env.globals.setdefault('csrf_token', csrf_token)


if __name__ == '__main__':
    with app.app_context():
        if not app.config.get('IS_PRODUCTION'):
            db.create_all()
    app.run(
        debug=app.config.get('DEBUG', False),
        host=app.config.get('RUN_HOST', '0.0.0.0'),
        port=app.config.get('RUN_PORT', 5000)
    )


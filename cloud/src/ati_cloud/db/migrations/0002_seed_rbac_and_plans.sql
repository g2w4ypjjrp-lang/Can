-- Rol bazlı yetkiler ve lisans paketleri için başlangıç verisi.
--
-- Paket fiyatları bilinçli olarak BOŞ bırakılmıştır ve paketler PASİF'tir. Fiyatlandırma
-- bir iş kararıdır; yönetici panelinden fiyat girilip paket etkinleştirilmeden satış
-- yapılamaz (license_plans_active_has_price kısıtı).

INSERT INTO admin_permissions (code, description) VALUES
    ('license.read',          'Lisansları görüntüleme'),
    ('license.generate',      'Tekil lisans üretme'),
    ('license.bulk_generate', 'Toplu lisans üretme'),
    ('license.cancel',        'Lisans iptal etme'),
    ('license.freeze',        'Lisans dondurma / çözme'),
    ('license.extend',        'Lisans süresi uzatma'),
    ('license.reveal_key',    'Tam lisans anahtarını görüntüleme (hassas)'),
    ('customer.read',         'Müşterileri görüntüleme'),
    ('customer.update',       'Müşteri bilgilerini düzenleme'),
    ('customer.block',        'Müşteri engelleme / engel kaldırma'),
    ('device.read',           'Cihazları görüntüleme'),
    ('device.revoke',         'Cihaz bağlantısını kaldırma'),
    ('order.read',            'Siparişleri görüntüleme'),
    ('payment.read',          'Ödemeleri görüntüleme'),
    ('payment.refund',        'İade başlatma'),
    ('plan.manage',           'Paket ve fiyat yönetimi'),
    ('report.sales',          'Satış raporları'),
    ('report.payments',       'Ödeme raporları'),
    ('report.usage',          'Kullanım istatistikleri'),
    ('admin.manage',          'Yönetici hesapları ve rolleri yönetme'),
    ('settings.manage',       'Sistem ayarlarını yönetme'),
    ('audit.read',            'Denetim kaydını görüntüleme');

INSERT INTO admin_roles (code, name, description) VALUES
    ('super_admin',     'Süper Yönetici',   'Tüm yetkiler'),
    ('license_manager', 'Lisans Yöneticisi', 'Lisans üretimi ve yaşam döngüsü yönetimi'),
    ('support',         'Destek',           'Müşteri ve cihaz desteği'),
    ('finance',         'Finans',           'Ödeme, iade ve satış raporları'),
    ('auditor',         'Denetçi',          'Salt okunur erişim ve denetim kaydı');

INSERT INTO admin_role_permissions (role_code, permission_code)
SELECT 'super_admin', code FROM admin_permissions;

INSERT INTO admin_role_permissions (role_code, permission_code) VALUES
    ('license_manager', 'license.read'),
    ('license_manager', 'license.generate'),
    ('license_manager', 'license.bulk_generate'),
    ('license_manager', 'license.cancel'),
    ('license_manager', 'license.freeze'),
    ('license_manager', 'license.extend'),
    ('license_manager', 'customer.read'),
    ('license_manager', 'device.read'),
    ('license_manager', 'device.revoke'),
    ('license_manager', 'report.usage'),
    ('support', 'license.read'),
    ('support', 'customer.read'),
    ('support', 'device.read'),
    ('support', 'device.revoke'),
    ('support', 'order.read'),
    ('finance', 'order.read'),
    ('finance', 'payment.read'),
    ('finance', 'payment.refund'),
    ('finance', 'report.sales'),
    ('finance', 'report.payments'),
    ('auditor', 'license.read'),
    ('auditor', 'customer.read'),
    ('auditor', 'device.read'),
    ('auditor', 'order.read'),
    ('auditor', 'payment.read'),
    ('auditor', 'report.sales'),
    ('auditor', 'report.payments'),
    ('auditor', 'report.usage'),
    ('auditor', 'audit.read');

-- Paketler: 6 süre x 3 cihaz limiti (deneme yalnızca 1 cihaz).
INSERT INTO license_plans (code, name, duration_days, device_limit, is_trial, sort_order)
VALUES ('trial_7d', '7 Günlük Deneme', 7, 1, true, 0);

INSERT INTO license_plans (code, name, duration_days, device_limit, sort_order)
SELECT
    format('%s_%sdev', d.code, c.devices),
    format('%s - %s Cihaz', d.label, c.devices),
    d.days,
    c.devices,
    d.ord * 10 + c.devices
FROM (VALUES
        ('d30',      '30 Gün',     30,   1),
        ('d90',      '90 Gün',     90,   2),
        ('d180',     '180 Gün',    180,  3),
        ('d365',     '365 Gün',    365,  4),
        ('lifetime', 'Ömür Boyu',  NULL, 5)
     ) AS d (code, label, days, ord)
CROSS JOIN (VALUES (1), (2), (3)) AS c (devices);

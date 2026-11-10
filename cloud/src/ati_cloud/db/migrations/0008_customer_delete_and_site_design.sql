-- Müşteri silme yetkisi ve site tasarım modu (yönetim panelinden seçilir).
--
-- Silme kişisel verileri anonimleştirir (customers.status = 'deleted'); siparişler yasal saklama
-- süresi boyunca korunur. Yetki yalnızca süper yöneticidedir ve doğrulama kodu (TOTP) ister.

INSERT INTO admin_permissions (code, description) VALUES
    ('customer.delete', 'Müşteri silme (kişisel veriler anonimleştirilir)');

INSERT INTO admin_role_permissions (role_code, permission_code) VALUES
    ('super_admin', 'customer.delete');

-- Site tasarım modu: herkese açık sayfaların renk/biçim teması. Varsayılan "okyanus".
INSERT INTO system_settings (key, value) VALUES ('appearance', '{"design": "okyanus"}')
ON CONFLICT (key) DO NOTHING;

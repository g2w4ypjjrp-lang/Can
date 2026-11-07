"""Güvenlik katmanı: motor durum makinesi, acil durdurma, hazırlık koşulları ve işlem modu kilidi.

Temel ilke: pozisyon *kapatmak* her zaman serbesttir (yalnızca azaltma/reduce-only), pozisyon
*açmak* ise yalnızca motor RUNNING durumundayken ve bütün güvenlik koşulları sağlandığında
mümkündür.
"""

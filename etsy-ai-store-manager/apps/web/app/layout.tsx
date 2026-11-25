import type { Metadata, Viewport } from 'next';
import './globals.css';
import { ServiceWorkerRegister } from '@/components/sw-register';

export const metadata: Metadata = {
  title: { default: 'Etsy AI Store Manager', template: '%s · Etsy AI Store Manager' },
  description: 'Etsy ve Printify mağaza yönetimi, kâr motoru ve AI destekli operasyon paneli',
  manifest: '/manifest.webmanifest',
  icons: { icon: '/icons/icon.svg', apple: '/icons/icon-192.png' },
  robots: { index: false, follow: false },
  appleWebApp: { capable: true, title: 'Store Manager', statusBarStyle: 'default' },
};

export const viewport: Viewport = {
  themeColor: '#10214a',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body className="min-h-screen font-sans">
        {children}
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}

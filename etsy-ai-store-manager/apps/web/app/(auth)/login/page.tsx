import type { Metadata } from 'next';
import { AuthForm } from '../auth-form';
import { signInAction } from '../actions';

export const metadata: Metadata = { title: 'Giriş' };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  return (
    <>
      <h1 className="mb-1 text-xl font-semibold text-navy-900">Giriş yap</h1>
      <p className="mb-6 text-sm text-slate-600">Mağaza yönetim panelinize erişin.</p>
      <AuthForm mode="login" action={signInAction} next={next} />
    </>
  );
}

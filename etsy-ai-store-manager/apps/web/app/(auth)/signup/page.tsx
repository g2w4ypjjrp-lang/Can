import type { Metadata } from 'next';
import { AuthForm } from '../auth-form';
import { signUpAction } from '../actions';

export const metadata: Metadata = { title: 'Kayıt' };

export default function SignupPage() {
  return (
    <>
      <h1 className="mb-1 text-xl font-semibold text-navy-900">Hesap oluştur</h1>
      <p className="mb-6 text-sm text-slate-600">Supabase Auth ile güvenli hesap.</p>
      <AuthForm mode="signup" action={signUpAction} />
    </>
  );
}

'use client';

import Link from 'next/link';
import { useActionState } from 'react';
import type { AuthFormState } from './actions';

export function AuthForm({
  mode,
  action,
  next,
}: {
  mode: 'login' | 'signup';
  action: (prev: AuthFormState, form: FormData) => Promise<AuthFormState>;
  next?: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  const isLogin = mode === 'login';
  return (
    <form action={formAction} className="space-y-4" noValidate>
      {next ? <input type="hidden" name="next" value={next} /> : null}
      {!isLogin && <Field label="Ad soyad" name="fullName" type="text" autoComplete="name" />}
      <Field label="E-posta" name="email" type="email" autoComplete="email" />
      <Field
        label="Parola"
        name="password"
        type="password"
        autoComplete={isLogin ? 'current-password' : 'new-password'}
        hint={isLogin ? undefined : 'En az 10 karakter'}
      />
      {state.error && (
        <p
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {state.error}
        </p>
      )}
      {state.info && (
        <p
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
        >
          {state.info}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-lg bg-navy-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60"
      >
        {pending ? 'Lütfen bekleyin…' : isLogin ? 'Giriş yap' : 'Hesap oluştur'}
      </button>
      <p className="text-center text-sm text-slate-600">
        {isLogin ? (
          <>
            Hesabınız yok mu?{' '}
            <Link href="/signup" className="font-medium text-brand-600 hover:underline">
              Kayıt olun
            </Link>
          </>
        ) : (
          <>
            Zaten hesabınız var mı?{' '}
            <Link href="/login" className="font-medium text-brand-600 hover:underline">
              Giriş yapın
            </Link>
          </>
        )}
      </p>
    </form>
  );
}

function Field(props: {
  label: string;
  name: string;
  type: string;
  autoComplete: string;
  hint?: string | undefined;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{props.label}</span>
      <input
        name={props.name}
        type={props.type}
        autoComplete={props.autoComplete}
        required
        className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
      />
      {props.hint && <span className="mt-1 block text-xs text-slate-500">{props.hint}</span>}
    </label>
  );
}

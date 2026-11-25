'use server';

import { redirect } from 'next/navigation';
import { z } from 'zod';
import { createSupabaseServerClient } from '@/lib/supabase/server';
import { webConfig } from '@/lib/config';

export interface AuthFormState {
  error?: string;
  info?: string;
}

const credentials = z.object({
  email: z.string().trim().toLowerCase().email('Geçerli bir e-posta girin'),
  password: z.string().min(10, 'Parola en az 10 karakter olmalı').max(128),
});

function safeNext(raw: FormDataEntryValue | null): string {
  const v = typeof raw === 'string' ? raw : '';
  // only same-site relative paths (prevents open redirects)
  return v.startsWith('/') && !v.startsWith('//') ? v : '/dashboard';
}

export async function signInAction(_prev: AuthFormState, form: FormData): Promise<AuthFormState> {
  const parsed = credentials.safeParse({
    email: form.get('email'),
    password: form.get('password'),
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? 'Geçersiz bilgiler' };
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signInWithPassword(parsed.data);
  if (error) return { error: 'E-posta veya parola hatalı' };
  redirect(safeNext(form.get('next')));
}

export async function signUpAction(_prev: AuthFormState, form: FormData): Promise<AuthFormState> {
  const parsed = credentials
    .extend({ fullName: z.string().trim().min(2, 'Ad soyad girin').max(120) })
    .safeParse({
      email: form.get('email'),
      password: form.get('password'),
      fullName: form.get('fullName'),
    });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? 'Geçersiz bilgiler' };
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase.auth.signUp({
    email: parsed.data.email,
    password: parsed.data.password,
    options: {
      data: { full_name: parsed.data.fullName },
      emailRedirectTo: `${webConfig().siteUrl}/auth/callback`,
    },
  });
  if (error) return { error: error.message };
  if (!data.session)
    return { info: 'Hesabınız oluşturuldu. E-postanıza gelen bağlantıyla doğrulayın.' };
  redirect('/dashboard');
}

export async function signOutAction() {
  const supabase = await createSupabaseServerClient();
  await supabase.auth.signOut();
  redirect('/login');
}

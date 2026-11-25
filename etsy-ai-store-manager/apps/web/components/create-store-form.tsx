'use client';

import { useActionState } from 'react';
import { STORE_LANGUAGES } from '@esm/shared';
import { createStoreAction, type FormState } from '@/app/dashboard/actions';

export function CreateStoreForm() {
  const [state, action, pending] = useActionState<FormState, FormData>(createStoreAction, {});
  return (
    <form action={action} className="grid gap-4 sm:grid-cols-3">
      <label className="sm:col-span-3">
        <span className="mb-1 block text-sm font-medium text-slate-700">Mağaza adı</span>
        <input
          name="name"
          required
          maxLength={120}
          placeholder="Etsy mağazanızın adı"
          className="w-full rounded-lg border border-line px-3 py-2 text-sm"
        />
      </label>
      <label>
        <span className="mb-1 block text-sm font-medium text-slate-700">Para birimi</span>
        <input
          name="currency"
          defaultValue="USD"
          maxLength={3}
          className="w-full rounded-lg border border-line px-3 py-2 text-sm uppercase"
        />
      </label>
      <label>
        <span className="mb-1 block text-sm font-medium text-slate-700">Varsayılan dil</span>
        <select
          name="defaultLanguage"
          defaultValue="en"
          className="w-full rounded-lg border border-line px-3 py-2 text-sm"
        >
          {STORE_LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-end">
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60"
        >
          {pending ? 'Oluşturuluyor…' : 'Mağaza kaydı oluştur'}
        </button>
      </div>
      {state.error && (
        <p role="alert" className="text-sm text-red-700 sm:col-span-3">
          {state.error}
        </p>
      )}
    </form>
  );
}

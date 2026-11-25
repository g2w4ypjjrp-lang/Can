// Next's standalone output does not include public/ and .next/static; copy them in.
import { cp } from 'node:fs/promises';
const target = '.next/standalone/apps/web';
await cp('public', `${target}/public`, { recursive: true });
await cp('.next/static', `${target}/.next/static`, { recursive: true });

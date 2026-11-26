import { describe, expect, it } from 'vitest';
import { normalizeTag, validateListingSeo } from '@esm/shared';
import { cleanTags, translationFactIssues } from '../../../apps/worker/src/seo/jobs.js';

const tags13 = [
  'botanical shirt',
  'plant lover gift',
  'fern t-shirt',
  'gardener gift',
  'grow slow',
  'houseplant tee',
  'minimal plant art',
  'nature lover gift',
  'plant mom shirt',
  'slow living',
  'green thumb gift',
  'leaf graphic tee',
  'fern lover',
];
const desc =
  'Botanical t-shirt with a hand-drawn fern and the words GROW SLOW. Soft unisex tee printed on demand by our production partner; a calm gift for gardeners and houseplant fans who enjoy slow living and minimal design. Sizes S to 3XL. Wash inside out on cold and hang to dry so the print stays crisp for years.';
const codes = (r: ReturnType<typeof validateListingSeo>) => r.issues.map((i) => i.code);

describe('validateListingSeo (Etsy rules)', () => {
  it('accepts a clean listing', () => {
    const r = validateListingSeo({
      title: 'Botanical T-Shirt, Grow Slow Fern Tee, Minimal Plant Lover Gift',
      description: desc,
      tags: tags13,
      materials: ['cotton'],
      primaryKeyword: 'botanical t-shirt',
    });
    expect(r.publishable).toBe(true);
    expect(r.issues.filter((i) => i.severity !== 'info')).toEqual([]);
    expect(r.score).toBeGreaterThanOrEqual(90);
  });

  it('enforces title length, characters and once-only symbols', () => {
    const r = validateListingSeo({ title: `${'a'.repeat(141)}`, description: desc, tags: tags13 });
    expect(codes(r)).toContain('title_too_long');
    expect(
      codes(validateListingSeo({ title: 'Fern tee 🌿 gift', description: desc, tags: tags13 })),
    ).toContain('title_invalid_chars');
    expect(
      codes(validateListingSeo({ title: 'Tee: fern: gift', description: desc, tags: tags13 })),
    ).toContain('title_char_repeat');
    // ™ © ® and one % : & + are allowed
    expect(
      validateListingSeo({
        title: 'Fern Tee™ & Mug: 100% cotton + gift',
        description: desc,
        tags: tags13,
      }).publishable,
    ).toBe(true);
  });

  it('detects keyword stuffing, all caps and spam claims', () => {
    const r = validateListingSeo({
      title: 'Plant Shirt Plant Lover Plant Gift BEST SELLER FREE SHIPPING',
      description: desc,
      tags: tags13,
    });
    expect(codes(r)).toEqual(
      expect.arrayContaining(['title_keyword_stuffing', 'title_all_caps', 'spam_phrases']),
    );
    expect(r.publishable).toBe(false);
  });

  it('checks tag count, length, characters and duplicates', () => {
    const r = validateListingSeo({
      title: 'Botanical Fern Tee',
      description: desc,
      tags: [...tags13, 'extra tag', 'this tag is far too long', 'fern lover', 'bad!tag'],
    });
    expect(codes(r)).toEqual(
      expect.arrayContaining([
        'tags_too_many',
        'tag_too_long',
        'tag_duplicate',
        'tag_invalid_chars',
      ]),
    );
    expect(
      codes(validateListingSeo({ title: 'Botanical Fern Tee', description: desc, tags: ['fern'] })),
    ).toContain('tags_unused_slots');
  });

  it('flags words repeated across most tags and short descriptions', () => {
    const r = validateListingSeo({
      title: 'Botanical Fern Tee for plant lovers',
      description: 'Nice tee',
      tags: ['plant a', 'plant b', 'plant c', 'plant d', 'plant e', 'plant f'],
    });
    expect(codes(r)).toEqual(expect.arrayContaining(['tags_word_overuse', 'description_short']));
  });

  it('validates materials characters', () => {
    expect(
      codes(
        validateListingSeo({
          title: 'Fern Tee',
          description: desc,
          tags: tags13,
          materials: ['100% cotton'],
        }),
      ),
    ).toContain('material_invalid_chars');
  });
});

describe('tag normalisation', () => {
  it('maps to Etsy characters, lower case and 20 characters', () => {
    expect(normalizeTag('Plant Lover Gift!')).toBe('plant lover gift');
    expect(normalizeTag("Mom's  #1 Gift")).toBe("mom's 1 gift");
    expect(normalizeTag('a very long tag that exceeds twenty')).toHaveLength(20);
    expect(cleanTags(['Fern', 'fern', 'Fern!', '', ...tags13])).toHaveLength(13);
    expect(cleanTags(['Fern', 'fern'])).toEqual(['fern']);
  });
});

describe('translation fact checks', () => {
  it('requires the numbers and printed text of the source', () => {
    const issues = translationFactIssues(
      { description: 'Mug 11 oz, 325 ml. Printed text GROW SLOW.' },
      { title: 'Tasse', description: 'Tasse 11 oz. Aufdruck Langsam wachsen.' },
      ['GROW SLOW'],
    );
    expect(issues.map((i) => i.code)).toEqual(
      expect.arrayContaining(['numbers_changed', 'printed_text_changed']),
    );
    expect(issues.find((i) => i.code === 'numbers_changed')!.message).toContain('325');
    expect(
      translationFactIssues(
        { description: 'Mug 11 oz, 325 ml.' },
        { title: 'Tasse GROW SLOW', description: 'Tasse 11 oz, 325 ml.' },
        ['GROW SLOW'],
      ),
    ).toEqual([]);
  });
});

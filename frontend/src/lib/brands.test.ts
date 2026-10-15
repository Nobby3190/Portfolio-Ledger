import { describe, expect, it } from 'vitest';
import { brandOf } from './brands';

describe('brandOf', () => {
  it('finds the brand a note names', () => {
    expect(brandOf('Netflix 家庭方案')).toBe('netflix');
    expect(brandOf('Claude Pro')).toBe('claude');
    expect(brandOf('支出 390 娛樂 @信用卡 # Spotify')).toBe('spotify');
    expect(brandOf('蝦皮購物')).toBe('shopee');
    expect(brandOf('ＮＥＴＦＬＩＸ')).toBe('netflix'); // full-width, from the 注音 IME
  });

  it('prefers the more specific name', () => {
    expect(brandOf('Uber Eats 晚餐')).toBe('ubereats');
    expect(brandOf('Uber 回家')).toBe('uber');
    expect(brandOf('Apple Music')).toBe('applemusic');
    expect(brandOf('YouTube Music')).toBe('youtubemusic');
  });

  it('needs a Latin word to stand alone', () => {
    expect(brandOf('LINE 貼圖')).toBe('line');
    expect(brandOf('online 課程')).toBeNull();
    expect(brandOf('午餐')).toBeNull();
    expect(brandOf(null)).toBeNull();
  });
});

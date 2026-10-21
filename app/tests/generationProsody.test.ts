import { describe, expect, test } from 'bun:test';
import { generationProsody, profileProsody } from '../src/lib/utils/generationProsody';

describe('generation delivery controls', () => {
  test('neutral controls override a slower, pitched profile', () => {
    const saved = profileProsody({
      default_emotion: 'calm',
      default_speed: 0.8,
      default_pitch: -2,
    });
    expect(saved).toEqual({ emotion: 'calm', speed: 0.8, pitch: -2 });
    expect(
      generationProsody('minimax', { ...saved, speed: 1, pitch: 0, emotion: undefined }),
    ).toEqual({ emotion: null, speed: 1, pitch: 0 });
  });
  test('switching to an unset voice clears the previous delivery', () => {
    expect(profileProsody({})).toEqual({ emotion: undefined, speed: 1, pitch: 0 });
  });
  test('does not send unsupported controls to local engines', () => {
    expect(generationProsody('qwen', { emotion: 'whisper', speed: 0.8, pitch: -2 })).toEqual({
      emotion: undefined,
      speed: undefined,
      pitch: undefined,
    });
  });
});

import type { EmotionValue, VoiceProfileResponse } from '@/lib/api/types';

export function profileProsody(
  profile: Pick<VoiceProfileResponse, 'default_emotion' | 'default_speed' | 'default_pitch'>,
) {
  return {
    emotion: (profile.default_emotion ?? undefined) as EmotionValue | undefined,
    speed: profile.default_speed ?? 1,
    pitch: profile.default_pitch ?? 0,
  };
}

export function generationProsody(
  engine: string | undefined,
  values: { emotion?: EmotionValue; speed?: number; pitch?: number },
) {
  return {
    // null explicitly selects automatic delivery; omission inherits profile defaults.
    emotion: engine === 'minimax' || engine === 'fish' ? (values.emotion ?? null) : undefined,
    speed: ['minimax', 'fish', 'kokoro'].includes(engine ?? '') ? values.speed : undefined,
    pitch: engine === 'minimax' ? values.pitch : undefined,
  };
}

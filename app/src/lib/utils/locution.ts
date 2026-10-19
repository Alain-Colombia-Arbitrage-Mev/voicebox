import script from '@/lib/constants/mantralia-claridad.json';

export function locutionText(engine: 'fish' | 'minimax') {
  return script.segments
    .map((segment) => {
      const emotion = engine === 'fish' ? `[${segment.emotion}] ` : '';
      return `${emotion}${segment.text} <#${segment.pause_after}#>`;
    })
    .join('\n');
}

export const locutionDirection = script.direction;
export const locutionSpeed = script.speed;

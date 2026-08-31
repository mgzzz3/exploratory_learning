import type { Game } from '../types/api'

export const BASIC_NOTICE = '未经联网核验'

export function getGameVerification(game: Game) {
  const isBasic = game.generation_mode === 'basic'
  return {
    isBasic,
    notice: isBasic ? BASIC_NOTICE : null,
    sources: isBasic || game.generation_mode === 'legacy' ? [] : game.sources || [],
    retrievedAt: isBasic || game.generation_mode === 'legacy' ? null : game.retrieved_at || null,
  }
}

export type Tier = 'novice' | 'advanced' | 'boss'
export type GameStatus = 'active' | 'paused' | 'completed'

export interface AuthUser {
  id: string
  nickname: string
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  user: AuthUser
}

export interface GameOption {
  index: number
  key: 'A' | 'B' | 'C'
  text: string
}

export interface GameLevel {
  position: number
  tier: Tier
  title: string
  intro: string
  question: string
  options: GameOption[]
}

export interface Game {
  id: string
  topic: string
  title: string
  status: GameStatus
  hearts: number
  current_level: number
  progress: number
  level: GameLevel | null
  summary: string[]
  elapsed_seconds: number | null
}

export type AnswerResult = 'correct' | 'wrong' | 'paused' | 'completed'

export interface AnswerResponse {
  result: AnswerResult
  message: string
  explanation: string | null
  game: Game
}

export interface ShareResponse {
  token: string
  path: string
  expires_at: string
}

export interface UserProfile {
  id: string
  nickname: string
  completed_games: number
  learned_points: number
  sound_enabled: boolean
  vibration_enabled: boolean
}

export interface UserSettings {
  sound_enabled: boolean
  vibration_enabled: boolean
}

export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
  }
}

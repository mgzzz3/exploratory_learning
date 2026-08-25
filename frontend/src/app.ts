import { PropsWithChildren } from 'react'
import './app.scss'

console.info(`[AI 万物学堂] env=${APP_ENV} api=${API_BASE_URL}`)

function App({ children }: PropsWithChildren<any>) {
  return children
}


export default App

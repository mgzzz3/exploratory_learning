import type { ComponentProps } from 'react'
import { Button } from '@tarojs/components'

type ButtonProps = ComponentProps<typeof Button>

export function PrimaryButton({ className = '', children, disabled, ...props }: ButtonProps) {
  return <Button className={`primary-action ${className}`} {...props} {...(disabled ? { disabled: true } : {})}>{children}</Button>
}

export function SecondaryButton({ className = '', children, disabled, ...props }: ButtonProps) {
  return <Button className={`secondary-action ${className}`} {...props} {...(disabled ? { disabled: true } : {})}>{children}</Button>
}

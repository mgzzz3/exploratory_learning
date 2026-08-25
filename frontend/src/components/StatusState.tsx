import { Input, Text, View } from '@tarojs/components'

import { PrimaryButton, SecondaryButton } from './ActionButton'

interface StatusStateProps {
  tone?: 'yellow' | 'red' | 'blue'
  icon: string
  title: string
  copy: string
  primaryText: string
  onPrimary: () => void
  secondaryText?: string
  onSecondary?: () => void
  input?: { value: string; placeholder: string; onInput: (value: string) => void }
}

export function StatusState(props: StatusStateProps) {
  return (
    <View className='error-state'>
      <View>
        <View className={`state-illustration state-illustration--${props.tone || 'yellow'}`}>
          <Text className='state-symbol'>{props.icon}</Text>
        </View>
        <Text className='state-title'>{props.title}</Text>
        <Text className='state-copy'>{props.copy}</Text>
        {props.input && (
          <Input
            className='topic-field'
            value={props.input.value}
            placeholder={props.input.placeholder}
            maxlength={80}
            onInput={(event) => props.input?.onInput(event.detail.value)}
          />
        )}
        <PrimaryButton onClick={props.onPrimary}>{props.primaryText}</PrimaryButton>
        {props.secondaryText && props.onSecondary && (
          <SecondaryButton className='action-gap' onClick={props.onSecondary}>
            {props.secondaryText}
          </SecondaryButton>
        )}
      </View>
    </View>
  )
}

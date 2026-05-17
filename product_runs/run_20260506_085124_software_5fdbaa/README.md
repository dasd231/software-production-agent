# Sandboxed Frontend Prototype

Goal:

```text
给我一个无敌华丽的网页，我不喜欢目前这个交互页面，最好跟豆包长得一样
```

Generation mode: `offline fallback`

Provider: `OPENAI`

Model: `gpt-4o-mini`

## Security Notes

The prototype is designed to be previewed through the product UI sandbox route. It is not
served with source-code privileges and should not be run as a trusted application.

Validation issues that triggered fallback or warnings:

- RateLimitError: Error code: 429 - {'error': {'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, read the docs: https://platform.openai.com/docs/guides/error-codes/api-errors.', 'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}}

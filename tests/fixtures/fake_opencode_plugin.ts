const schema: any = new Proxy(
  () => schema,
  {
    apply: () => schema,
    get: () => schema,
  },
)

export const tool: any = Object.assign((definition: any) => definition, { schema })
export type Plugin = any

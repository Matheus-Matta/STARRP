/** Substituto do Vue para os arquivos da retaguarda: diálogo/tela própria vira um marcador. */
export const WEB_ONLY = "__starrpWebOnly";

export function defineAsyncComponent(_loader: unknown) {
  return { [WEB_ONLY]: true };
}

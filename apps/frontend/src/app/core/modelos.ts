/** Contrato con la API (apps/api/src/copiloto_api/main.py). */

export type Rol = 'asesor' | 'supervisor' | 'admin';

export interface Usuario {
  id: string;
  rol: Rol;
  nombre: string;
}

export interface Fuente {
  n: number;
  doc_id: string;
  titulo: string;
  version: string;
  seccion: string | null;
  fuente: string;
  pagina: number | null;
  relevancia: number;
  citada: boolean;
  extracto?: string;
}

export interface Propuesta {
  propuesta_id: string;
  accion: string;
  resumen: string;
  requiere_rol: Rol;
}

export interface ToolUsada {
  nombre: string;
  ok: boolean;
  ms?: number;
  automatica?: boolean;
}

export interface RiesgoChurn {
  nivel: 'alto' | 'medio' | 'bajo';
  probabilidad: number;
  factores: { variable: string; descripcion: string; aporte: number }[];
  version?: string;
}

export interface Resultado {
  turno_id: string;
  sesion_id: string;
  respuesta: string;
  confianza: number | null;
  intencion: string | null;
  cliente_id: string | null;
  riesgo_churn: RiesgoChurn | null;
  ruta: 'agente' | 'escalar' | 'fuera_alcance' | 'bloqueado';
  motivo: string | null;
  fuentes: Fuente[];
  tools: ToolUsada[];
  propuestas: Propuesta[];
  sin_cita: boolean;
  advertencias: string[];
  modelo: string | null;
  uso: { tokens_entrada: number; tokens_salida: number; costo_usd: number; llamadas: number };
  latencias: { ttft_ms: number; total_ms: number };
}

/** Eventos SSE de POST /chat, en el orden en que llegan. */
export type EventoChat =
  | { tipo: 'inicio'; datos: { sesion_id: string; turno_id: string } }
  | { tipo: 'estado'; datos: { paso: string } }
  | { tipo: 'token'; datos: { texto: string } }
  | { tipo: 'reiniciar'; datos: Record<string, never> }
  | { tipo: 'reemplazar'; datos: { texto: string } }
  | { tipo: 'tool'; datos: { nombre: string; ok: boolean } }
  | { tipo: 'propuesta'; datos: Propuesta }
  | { tipo: 'fuentes'; datos: { fuentes: Fuente[] } }
  | { tipo: 'fin'; datos: Resultado }
  | { tipo: 'error'; datos: { mensaje: string } };

export interface FichaCliente {
  cliente: {
    cliente_id: string;
    nombre: string;
    ciudad?: string;
    segmento?: string;
    antiguedad_meses?: number;
    dias_mora?: number;
    estado?: string;
    valor_mensual_total?: number;
    servicios?: {
      servicio_id?: string;
      tipo?: string;
      plan?: string;
      valor_mensual?: number;
      estado?: string;
    }[];
    tickets_recientes?: { ticket_id?: string; fecha: string; categoria?: string; estado?: string }[];
    ofertas_retencion_12m?: { fecha: string; codigo?: string }[];
  };
  saldo: { saldo_pendiente: number; saldo_vencido: number; proxima_fecha_limite: string | null } | null;
  facturas:
    | { factura_id: string; periodo: string; valor_total: number; estado: string; fecha_limite_pago: string }[]
    | null;
}

export interface Pendiente extends Propuesta {
  usuario: string;
  sesion_id: string;
  creada: number;
}

export interface EscalamientoAbierto {
  escalamiento_id: string;
  sesion_id: string;
  turno_id: string | null;
  cliente_id: string | null;
  motivo: string;
  usuario: string;
  fecha: string;
}

export interface TurnoGuardado {
  turno_id: string;
  fecha: string;
  pregunta: string;
  respuesta: string;
  ruta: string;
  confianza: number | null;
}

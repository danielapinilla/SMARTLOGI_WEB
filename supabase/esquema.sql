-- =====================================================
-- SMARTLOGIC · Base de datos para varias empresas
-- Pegar completo en Supabase > SQL Editor > New query > Run
-- Se puede ejecutar más de una vez sin problema.
-- =====================================================

-- ---------- Empresas y sus usuarios ----------

create table if not exists empresas (
    id          uuid primary key default gen_random_uuid(),
    nombre      text not null,
    creada_en   timestamptz not null default now()
);

create table if not exists miembros (
    user_id     uuid primary key references auth.users (id) on delete cascade,
    empresa_id  uuid not null references empresas (id) on delete cascade,
    nombre      text,
    rol         text not null default 'admin',
    creado_en   timestamptz not null default now()
);

-- ---------- Datos de cada empresa ----------
-- Mismas columnas que los CSV de la demo, más empresa_id.
-- Las fechas van como número AAAAMMDD (ej. 20260108), igual que en los CSV.

create table if not exists clientes (
    empresa_id uuid not null references empresas (id) on delete cascade,
    cliente_id bigint not null,
    nombre_cliente text, tipo_cliente text, comuna text, ciudad text,
    fecha_registro text, segmento text,
    primary key (empresa_id, cliente_id)
);

create table if not exists conductores (
    empresa_id uuid not null references empresas (id) on delete cascade,
    conductor_id bigint not null,
    nombre_conductor text, fecha_ingreso text, experiencia_anios integer,
    tipo_licencia text, estado text,
    primary key (empresa_id, conductor_id)
);

create table if not exists rutas (
    empresa_id uuid not null references empresas (id) on delete cascade,
    ruta_id bigint not null,
    nombre_ruta text, comuna_origen text, comuna_destino text,
    distancia_km numeric, tiempo_estimado_min integer,
    nivel_trafico_habitual text, tipo_ruta text, peajes integer, estado text,
    primary key (empresa_id, ruta_id)
);

create table if not exists vehiculos (
    empresa_id uuid not null references empresas (id) on delete cascade,
    vehiculo_id bigint not null,
    patente text, tipo_vehiculo text, marca text, modelo text, anio integer,
    capacidad_kg integer, combustible text, fecha_alta text, estado text,
    primary key (empresa_id, vehiculo_id)
);

create table if not exists pedidos (
    empresa_id uuid not null references empresas (id) on delete cascade,
    pedido_id bigint not null,
    cliente_id bigint, fecha_pedido_id integer, tipo_servicio text,
    cantidad_paquetes integer, peso_total_kg numeric, prioridad text,
    valor_pedido numeric, comuna_entrega text, estado_pedido text,
    primary key (empresa_id, pedido_id)
);

create table if not exists entregas (
    empresa_id uuid not null references empresas (id) on delete cascade,
    entrega_id bigint not null,
    pedido_id bigint, fecha_salida_id integer, fecha_entrega_id integer,
    conductor_id bigint, vehiculo_id bigint, ruta_id bigint,
    hora_salida text, hora_entrega text, tiempo_real_min integer,
    tiempo_estimado_min integer, retraso_min integer,
    entrega_a_tiempo text, estado_entrega text,
    primary key (empresa_id, entrega_id)
);

create table if not exists mantenciones (
    empresa_id uuid not null references empresas (id) on delete cascade,
    mantencion_id bigint not null,
    vehiculo_id bigint, fecha_mantencion_id integer, tipo_mantencion text,
    descripcion text, costo numeric, kilometraje integer,
    dias_fuera_servicio integer, taller text, resultado text,
    primary key (empresa_id, mantencion_id)
);

create table if not exists combustible (
    empresa_id uuid not null references empresas (id) on delete cascade,
    combustible_id bigint not null,
    vehiculo_id bigint, fecha_id integer, litros_cargados numeric,
    precio_litro numeric, costo_total numeric, kilometraje_actual integer,
    tipo_combustible text, estacion_carga text,
    primary key (empresa_id, combustible_id)
);

create table if not exists incidentes (
    empresa_id uuid not null references empresas (id) on delete cascade,
    incidente_id bigint not null,
    entrega_id bigint, fecha_incidente_id integer, vehiculo_id bigint,
    conductor_id bigint, tipo_incidente text, gravedad text, descripcion text,
    tiempo_perdido_min integer, costo_estimado numeric, resuelto text,
    primary key (empresa_id, incidente_id)
);

-- ---------- Seguridad ----------
-- Se activa la seguridad por filas (RLS) SIN reglas de acceso: así nadie
-- puede leer ni escribir estas tablas con la clave pública del navegador.
-- Solo el servidor de SmartLogic (con la clave secreta) accede, y siempre
-- filtra por la empresa de la persona que inició sesión.

alter table empresas     enable row level security;
alter table miembros     enable row level security;
alter table clientes     enable row level security;
alter table conductores  enable row level security;
alter table rutas        enable row level security;
alter table vehiculos    enable row level security;
alter table pedidos      enable row level security;
alter table entregas     enable row level security;
alter table mantenciones enable row level security;
alter table combustible  enable row level security;
alter table incidentes   enable row level security;

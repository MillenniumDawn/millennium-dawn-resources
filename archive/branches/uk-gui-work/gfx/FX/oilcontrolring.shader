Includes = {
}

PixelShader =
{
	Samplers =
	{
		TextureOne =
		{
			Index = 0
			MagFilter = "Linear"
			MinFilter = "Linear"
			MipFilter = "None"
			AddressU = "Wrap"
			AddressV = "Wrap"
		}
		TextureTwo =
		{
			Index = 1
			MagFilter = "Linear"
			MinFilter = "Linear"
			MipFilter = "None"
			AddressU = "Wrap"
			AddressV = "Wrap"
		}
	}
}


VertexStruct VS_INPUT
{
    float4 vPosition  : POSITION;
    float2 vTexCoord  : TEXCOORD0;
};

VertexStruct VS_OUTPUT
{
    float4  vPosition : PDX_POSITION;
    float2  vTexCoord0 : TEXCOORD0;
};


ConstantBuffer( 0, 0 )
{
	float4x4 WorldViewProjectionMatrix;
	float4 vFirstColor;   // .r encodes zone: 0.0=danger 0.5=warning 1.0=healthy
	float4 vSecondColor;  // empty track color
	float CurrentState;   // oil control 0.0 - 1.0
};


VertexShader =
{
	MainCode VertexShader
	[[
		VS_OUTPUT main(const VS_INPUT v)
		{
			VS_OUTPUT Out;
			Out.vPosition  = mul(WorldViewProjectionMatrix, v.vPosition);
			Out.vTexCoord0 = v.vTexCoord;
			return Out;
		}
	]]
}

PixelShader =
{
	MainCode PixelColor
	[[
		float4 main(VS_OUTPUT v) : PDX_COLOR
		{
			float TWO_PI = 6.283185307f;

			// ── 1. UV + distance from center ────────────────────────────────
			float2 uv   = v.vTexCoord0 - 0.5f;
			float  dist = length(uv);

			// ── 2. Donut bounds ──────────────────────────────────────────────
			float outerR = 0.50f;
			float innerR = 0.30f;
			if (dist > outerR) discard;
			if (dist < innerR) discard;

			// ── 3. Angle — clockwise from 12 o'clock ────────────────────────
			float angle = atan2(uv.y, -uv.x) - 1.5707963268f;
			if (angle < 0.0f) angle += TWO_PI;

			// ── 4. Fill threshold ────────────────────────────────────────────
			float fillAngle = CurrentState * TWO_PI;
			bool  filled    = (angle < fillAngle);

			// ── 5. Zone color ────────────────────────────────────────────────
			float4 dangerColor  = float4(0.75f, 0.12f, 0.10f, 1.0f);
			float4 warningColor = float4(0.82f, 0.52f, 0.08f, 1.0f);
			float4 healthyColor = float4(0.22f, 0.48f, 0.18f, 1.0f);

			float4 zoneColor;
			if      (vFirstColor.r < 0.25f) zoneColor = dangerColor;
			else if (vFirstColor.r < 0.75f) zoneColor = warningColor;
			else                            zoneColor = healthyColor;

			// ── 6. Empty track ───────────────────────────────────────────────
			if (!filled)
			{
				float outerEdge   = smoothstep(outerR - 0.008f, outerR, dist);
				float4 emptyColor = lerp(vSecondColor, float4(0,0,0,0), outerEdge);
				return clamp(emptyColor, 0.0f, 1.0f);
			}

			// ── 7. Smooth gradient arc ───────────────────────────────────────
			//    Dark at 12 o'clock origin, brightening toward fill edge.
			float gradT      = clamp(angle / (fillAngle + 0.001f), 0.0f, 1.0f);
			float4 gradColor = lerp(zoneColor * 0.55f, zoneColor, gradT);

			// ── 8. Outer edge anti-alias ─────────────────────────────────────
			float outerEdge  = smoothstep(outerR - 0.008f, outerR, dist);
			gradColor.a      = lerp(gradColor.a, 0.0f, outerEdge);

			return clamp(gradColor, 0.0f, 1.0f);
		}
	]]

	MainCode PixelTexture
	[[
		float4 main(VS_OUTPUT v) : PDX_COLOR
		{
			return float4(1, 1, 1, 1);
		}
	]]
}


BlendState BlendState
{
	BlendEnable = yes
	SourceBlend = "SRC_ALPHA"
	DestBlend = "INV_SRC_ALPHA"
}


Effect Color
{
	VertexShader = "VertexShader"
	PixelShader = "PixelColor"
}

Effect Texture
{
	VertexShader = "VertexShader"
	PixelShader = "PixelTexture"
}

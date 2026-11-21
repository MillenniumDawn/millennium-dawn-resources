Includes = {
}

PixelShader =
{
	Samplers =
	{
		TextureOne =
		{
			Index = 0
			MagFilter = "Point"
			MinFilter = "Point"
			MipFilter = "None"
			AddressU = "Wrap"
			AddressV = "Wrap"
		}
		TextureTwo =
		{
			Index = 1
			MagFilter = "Point"
			MinFilter = "Point"
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
	float4 vFirstColor;
	float4 vSecondColor;
	float CurrentState;
};


VertexShader =
{
	MainCode VertexShader
	[[
		
		VS_OUTPUT main(const VS_INPUT v )
		{
			VS_OUTPUT Out;
		   	Out.vPosition  = mul( WorldViewProjectionMatrix, v.vPosition );
			Out.vTexCoord0  = v.vTexCoord;

			return Out;
		}
		
	]]
}

PixelShader =
{
	MainCode PixelColor
	[[
		
		float4 main( VS_OUTPUT v ) : PDX_COLOR
		{
			float2 uv = v.vTexCoord0 - 0.5f;
			float dist = length(uv);
			float outerRadius = 0.5f;
			float innerRadius = 0.3f;
			float aaWidth = 0.02f;

			// Ring mask with smooth AA on both edges
			float maskOuter = smoothstep(outerRadius, outerRadius - aaWidth, dist);
			float maskInner = smoothstep(innerRadius, innerRadius + aaWidth, dist);
			float ringMask  = maskOuter * maskInner;
			ringMask        = ringMask * ringMask; // squared for extra softness

			// Angle (0 = top, clockwise)
			float angle = atan2(uv.y, -uv.x) - 1.5707963268f;
			if (angle < 0.0f) angle += 6.283185307f;

			float progress = CurrentState * 6.283185307f;

			float4 col;
			if (angle < progress)
			{
				col = vFirstColor;

				float gradT = clamp(angle / (progress + 0.001f), 0.0f, 1.0f);
				col.rgb    *= lerp(0.45f, 1.0f, gradT);
			}
			else
			{
				col = vSecondColor;
			}

			float bevelBright = smoothstep(0.0f, 1.0f, ringDepth);
			float bevel       = lerp(-0.08f, 0.10f, bevelBright);
			col.rgb          += bevel;

			 // Inner shadow — stronger, tighter falloff
			float innerShadow  = 1.0f - smoothstep(0.0f, 0.28f, ringDepth);
			innerShadow        = innerShadow * innerShadow * innerShadow;
			col.rgb  

			col.a *= ringMask;
			return col;
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


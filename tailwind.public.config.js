module.exports = {
    content: [
        './templates/_public_base.html',
        './templates/public_landing.html',
        './templates/public_pricing.html',
        './templates/public_solution.html',
        './templates/public_privacy.html',
        './templates/public_kvkk.html',
        './templates/public_terms.html'
    ],
    theme: {
        extend: {
            colors: {
                primary: {
                    50: '#eff6ff',
                    100: '#dbeafe',
                    200: '#bfdbfe',
                    300: '#93c5fd',
                    400: '#60a5fa',
                    500: '#3b82f6',
                    600: '#2563eb',
                    700: '#1d4ed8',
                    800: '#1e40af',
                    900: '#1e3a8a',
                    950: '#172554'
                }
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif']
            }
        }
    },
    plugins: []
};

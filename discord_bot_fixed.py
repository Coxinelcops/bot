const { Client, GatewayIntentBits, EmbedBuilder } = require('discord.js');
const axios = require('axios');

class PlayerMonitor {
    constructor(token, channelId) {
        this.client = new Client({
            intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent]
        });
        
        this.token = token;
        this.channelId = channelId;
        this.monitoredUrls = new Map(); // URL -> { isOffline: boolean, consecutiveErrors: number, lastCheck: Date }
        this.offlineMessage = "Veuillez réessayer quand l'invocateur sera dans une partie.";
        this.checkInterval = 3 * 60 * 1000; // 3 minutes
        this.maxConsecutiveErrors = 3; // Éviter les faux positifs dus aux erreurs de site
        
        this.setupBot();
    }

    setupBot() {
        this.client.on('ready', () => {
            console.log(`Bot connecté en tant que ${this.client.user.tag}`);
            this.startMonitoring();
        });

        this.client.on('messageCreate', async (message) => {
            if (message.author.bot) return;
            await this.handleCommands(message);
        });

        this.client.login(this.token);
    }

    async handleCommands(message) {
        const content = message.content.toLowerCase().trim();
        
        if (content.startsWith('!monitor ')) {
            const url = content.slice(9).trim();
            if (this.isValidUrl(url)) {
                await this.addMonitoring(url, message);
            } else {
                message.reply('❌ URL invalide. Veuillez fournir une URL valide.');
            }
        }
        
        else if (content === '!list') {
            await this.listMonitored(message);
        }
        
        else if (content.startsWith('!remove ')) {
            const url = content.slice(8).trim();
            await this.removeMonitoring(url, message);
        }
        
        else if (content === '!help') {
            await this.showHelp(message);
        }
    }

    isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }

    async addMonitoring(url, message) {
        if (this.monitoredUrls.has(url)) {
            message.reply('🔍 Cette URL est déjà surveillée.');
            return;
        }

        // Test initial de l'URL
        try {
            const response = await this.checkUrl(url);
            const isOffline = response.includes(this.offlineMessage);
            
            this.monitoredUrls.set(url, {
                isOffline: isOffline,
                consecutiveErrors: 0,
                lastCheck: new Date(),
                addedBy: message.author.id
            });

            const embed = new EmbedBuilder()
                .setColor(isOffline ? 0xff0000 : 0x00ff00)
                .setTitle('🔍 Surveillance ajoutée')
                .setDescription(`URL: ${url}`)
                .addFields(
                    { name: 'Statut actuel', value: isOffline ? '🔴 Hors ligne' : '🟢 En ligne' },
                    { name: 'Vérification', value: 'Toutes les 3 minutes' }
                )
                .setTimestamp();

            message.reply({ embeds: [embed] });
            console.log(`Surveillance ajoutée pour: ${url} (Statut: ${isOffline ? 'Hors ligne' : 'En ligne'})`);
            
        } catch (error) {
            message.reply('❌ Impossible de vérifier l\'URL. Vérifiez qu\'elle est accessible.');
            console.error('Erreur lors du test initial:', error.message);
        }
    }

    async removeMonitoring(url, message) {
        if (this.monitoredUrls.has(url)) {
            this.monitoredUrls.delete(url);
            message.reply(`✅ Surveillance supprimée pour: ${url}`);
            console.log(`Surveillance supprimée pour: ${url}`);
        } else {
            message.reply('❌ Cette URL n\'est pas surveillée.');
        }
    }

    async listMonitored(message) {
        if (this.monitoredUrls.size === 0) {
            message.reply('📝 Aucune URL surveillée actuellement.');
            return;
        }

        const embed = new EmbedBuilder()
            .setColor(0x0099ff)
            .setTitle('📋 URLs Surveillées')
            .setTimestamp();

        let description = '';
        for (const [url, data] of this.monitoredUrls) {
            const status = data.isOffline ? '🔴 Hors ligne' : '🟢 En ligne';
            const lastCheck = data.lastCheck.toLocaleString('fr-FR');
            description += `**${url}**\n${status} - Dernière vérif: ${lastCheck}\n\n`;
        }

        embed.setDescription(description);
        message.reply({ embeds: [embed] });
    }

    async showHelp(message) {
        const embed = new EmbedBuilder()
            .setColor(0x0099ff)
            .setTitle('🤖 Aide - Bot Surveillant de Joueur')
            .setDescription('Commandes disponibles:')
            .addFields(
                { name: '!monitor <URL>', value: 'Ajouter une URL à surveiller' },
                { name: '!list', value: 'Afficher toutes les URLs surveillées' },
                { name: '!remove <URL>', value: 'Supprimer une URL de la surveillance' },
                { name: '!help', value: 'Afficher cette aide' }
            )
            .addFields(
                { name: 'ℹ️ Fonctionnement', value: 'Le bot vérifie toutes les 3 minutes si le message "Veuillez réessayer quand l\'invocateur sera dans une partie." est présent sur les pages surveillées.' },
                { name: '🛡️ Protection', value: 'Système anti-faux positifs avec vérifications multiples avant notification.' }
            )
            .setTimestamp();

        message.reply({ embeds: [embed] });
    }

    async checkUrl(url) {
        const response = await axios.get(url, {
            timeout: 10000,
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        });
        return response.data;
    }

    startMonitoring() {
        setInterval(async () => {
            for (const [url, data] of this.monitoredUrls) {
                try {
                    const content = await this.checkUrl(url);
                    const isCurrentlyOffline = content.includes(this.offlineMessage);
                    
                    // Reset du compteur d'erreurs si la vérification réussit
                    data.consecutiveErrors = 0;
                    data.lastCheck = new Date();

                    // Vérifier s'il y a un changement de statut
                    if (data.isOffline && !isCurrentlyOffline) {
                        // Le joueur est maintenant EN LIGNE
                        await this.sendNotification(url, true);
                        data.isOffline = false;
                        console.log(`🟢 ${url} - Joueur EN LIGNE`);
                    } else if (!data.isOffline && isCurrentlyOffline) {
                        // Le joueur est maintenant HORS LIGNE
                        await this.sendNotification(url, false);
                        data.isOffline = true;
                        console.log(`🔴 ${url} - Joueur HORS LIGNE`);
                    }

                } catch (error) {
                    data.consecutiveErrors++;
                    console.error(`Erreur lors de la vérification de ${url}:`, error.message);
                    
                    // Si trop d'erreurs consécutives, considérer comme potentiellement hors ligne
                    // mais seulement après plusieurs tentatives pour éviter les faux positifs
                    if (data.consecutiveErrors >= this.maxConsecutiveErrors && !data.isOffline) {
                        console.warn(`⚠️ Trop d'erreurs consécutives pour ${url}, possible changement de statut`);
                        // Optionnel: envoyer une notification d'erreur
                        await this.sendErrorNotification(url, error.message);
                    }
                }
            }
        }, this.checkInterval);

        console.log('🔍 Surveillance démarrée - Vérification toutes les 3 minutes');
    }

    async sendNotification(url, isOnline) {
        const channel = this.client.channels.cache.get(this.channelId);
        if (!channel) {
            console.error('Canal Discord introuvable');
            return;
        }

        const embed = new EmbedBuilder()
            .setColor(isOnline ? 0x00ff00 : 0xff0000)
            .setTitle(isOnline ? '🟢 Joueur EN LIGNE!' : '🔴 Joueur HORS LIGNE')
            .setDescription(`**URL:** ${url}`)
            .addFields({
                name: 'Statut',
                value: isOnline ? 
                    '✅ Le joueur est maintenant disponible pour jouer!' :
                    '❌ Le joueur n\'est plus en ligne'
            })
            .setTimestamp()
            .setFooter({ text: 'Surveillance automatique' });

        await channel.send({ embeds: [embed] });
    }

    async sendErrorNotification(url, errorMessage) {
        const channel = this.client.channels.cache.get(this.channelId);
        if (!channel) return;

        const embed = new EmbedBuilder()
            .setColor(0xffaa00)
            .setTitle('⚠️ Erreur de surveillance')
            .setDescription(`Problème lors de la vérification de: ${url}`)
            .addFields({
                name: 'Erreur',
                value: errorMessage.substring(0, 1000) // Limiter la taille
            })
            .setTimestamp();

        await channel.send({ embeds: [embed] });
    }
}

// Configuration - REMPLACEZ PAR VOS VRAIES VALEURS
const DISCORD_TOKEN = 'VOTRE_TOKEN_BOT_DISCORD';
const CHANNEL_ID = 'VOTRE_ID_CANAL_DISCORD';

// Démarrage du bot
const monitor = new PlayerMonitor(DISCORD_TOKEN, CHANNEL_ID);

// Gestion propre de l'arrêt
process.on('SIGINT', () => {
    console.log('Arrêt du bot...');
    monitor.client.destroy();
    process.exit(0);
});

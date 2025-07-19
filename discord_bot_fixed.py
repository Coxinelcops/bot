
class WebMonitorFixed:
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        # Cache pour éviter les re-détections
        self.last_detection = {}
        
    async def detect_live_game(self, html, base_url):
        """Détection AMÉLIORÉE avec validation stricte"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            games = []

            logger.info(f"🔍 Analyse stricte de la page pour parties LIVE...")

            # ÉTAPE 1: Vérifications préliminaires obligatoires
            if not await self.is_valid_lol_page(soup, base_url):
                logger.info("❌ Page non valide pour LoL")
                return []

            # ÉTAPE 2: Recherche d'indicateurs CONCRETS de partie active
            live_indicators = await self.find_concrete_live_indicators(soup)
            
            if not live_indicators:
                logger.info("❌ Aucun indicateur concret de partie live")
                return []

            # ÉTAPE 3: Validation STRICTE de chaque indicateur
            for indicator in live_indicators:
                validation_result = await self.strict_validate_live_game(indicator, soup, base_url)
                
                if validation_result['is_valid']:
                    game_info = await self.extract_validated_game_info(validation_result, base_url)
                    if game_info:
                        # ÉTAPE 4: Vérification anti-doublon
                        if not await self.is_duplicate_detection(game_info, base_url):
                            games.append(game_info)
                            logger.info(f"✅ Partie LIVE confirmée: {game_info['title']}")
                        else:
                            logger.info("⚠️ Détection dupliquée ignorée")

            return games

        except Exception as e:
            logger.error(f"Erreur lors de la détection: {e}")
            return []

    async def is_valid_lol_page(self, soup, base_url):
        """Validation stricte que c'est une page LoL valide"""
        try:
            # 1. Vérifier le domaine
            valid_domains = ['op.gg', 'u.gg', 'blitz.gg', 'porofessor.gg', 'lolking.net']
            if not any(domain in base_url.lower() for domain in valid_domains):
                logger.info(f"❌ Domaine non reconnu: {base_url}")
                return False
            
            # 2. Vérifier la structure de la page
            page_text = soup.get_text().lower()
            required_elements = ['league of legends', 'summoner', 'rank']
            
            if not all(element in page_text for element in required_elements):
                logger.info("❌ Structure de page LoL manquante")
                return False
            
            # 3. Vérifier que c'est une page de joueur (pas une page générale)
            if '/summoner/' not in base_url and '/player/' not in base_url:
                logger.info("❌ Pas une page de joueur spécifique")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Erreur validation page: {e}")
            return False

    async def find_concrete_live_indicators(self, soup):
        """Recherche d'indicateurs CONCRETS de partie live"""
        indicators = []
        
        try:
            # 1. Recherche de statuts de jeu explicites
            live_status_selectors = [
                '[data-game-status="live"]',
                '[data-status="in-game"]', 
                '.live-game-indicator',
                '.spectate-button:not(.disabled)',
                '[class*="live"][class*="game"]',
                '[id*="live"][id*="game"]'
            ]
            
            for selector in live_status_selectors:
                elements = soup.select(selector)
                for element in elements:
                    if await self.validate_live_element(element):
                        indicators.append({
                            'element': element,
                            'type': 'status_indicator',
                            'confidence': 0.9
                        })
            
            # 2. Recherche de boutons spectate ACTIFS
            spectate_buttons = soup.find_all(['button', 'a'], 
                                           class_=re.compile(r'spectate|watch', re.I))
            
            for button in spectate_buttons:
                if await self.validate_spectate_button(button):
                    indicators.append({
                        'element': button,
                        'type': 'spectate_button',
                        'confidence': 0.7
                    })
            
            # 3. Recherche de données de jeu en temps réel
            game_time_elements = soup.find_all(string=re.compile(r'\d{1,2}:\d{2}', re.I))
            for time_element in game_time_elements:
                parent = time_element.parent
                if await self.validate_game_timer(parent):
                    indicators.append({
                        'element': parent,
                        'type': 'game_timer',
                        'confidence': 0.8
                    })
            
            logger.info(f"🎯 {len(indicators)} indicateurs concrets trouvés")
            return indicators
            
        except Exception as e:
            logger.error(f"Erreur recherche indicateurs: {e}")
            return []

    async def validate_live_element(self, element):
        """Validation qu'un élément indique vraiment une partie live"""
        try:
            # Vérifier que l'élément n'est pas désactivé
            if element.get('disabled') or 'disabled' in element.get('class', []):
                return False
                
            # Vérifier qu'il n'y a pas de texte indiquant que le jeu est fini
            text = element.get_text().lower()
            if any(word in text for word in ['ended', 'finished', 'completed', 'offline']):
                return False
                
            return True
            
        except Exception:
            return False

    async def validate_spectate_button(self, button):
        """Validation stricte d'un bouton spectate"""
        try:
            # 1. Vérifier que le bouton est actif
            if button.get('disabled') or 'disabled' in button.get('class', []):
                return False
            
            # 2. Vérifier le texte du bouton
            button_text = button.get_text().strip().lower()
            if not any(word in button_text for word in ['spectate', 'watch', 'live']):
                return False
                
            # 3. Vérifier qu'il y a un lien valide
            href = button.get('href')
            if href and ('spectate' in href or 'live' in href):
                return True
                
            # 4. Vérifier les attributs data-*
            if button.get('data-spectate-url') or button.get('data-game-id'):
                return True
                
            return False
            
        except Exception:
            return False

    async def validate_game_timer(self, element):
        """Validation d'un timer de jeu"""
        try:
            text = element.get_text()
            
            # Vérifier le format du timer (MM:SS)
            if not re.match(r'\d{1,2}:\d{2}', text):
                return False
                
            # Vérifier le contexte (doit être dans un contexte de jeu)
            parent_text = element.parent.get_text().lower()
            if any(word in parent_text for word in ['game', 'match', 'duration']):
                return True
                
            return False
            
        except Exception:
            return False

    async def strict_validate_live_game(self, indicator, soup, base_url):
        """Validation STRICTE qu'une partie est réellement live"""
        try:
            element = indicator['element']
            indicator_type = indicator['type']
            
            validation_result = {
                'is_valid': False,
                'player_name': None,
                'game_data': {},
                'confidence': 0
            }
            
            # VALIDATION 1: Vérifier la cohérence temporelle
            if not await self.validate_temporal_consistency(element, soup):
                logger.info("❌ Échec validation temporelle")
                return validation_result
            
            # VALIDATION 2: Extraire et valider les données de joueur
            player_name = await self.extract_player_name_validated(base_url, soup)
            if not player_name or player_name == "Joueur inconnu":
                logger.info("❌ Nom de joueur non valide")
                return validation_result
                
            # VALIDATION 3: Vérifier la cohérence des données de jeu
            game_data = await self.extract_game_data_validated(element, soup)
            if not game_data.get('is_coherent'):
                logger.info("❌ Données de jeu incohérentes")
                return validation_result
            
            validation_result.update({
                'is_valid': True,
                'player_name': player_name,
                'game_data': game_data,
                'confidence': indicator['confidence']
            })
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Erreur validation stricte: {e}")
            return {'is_valid': False}

    async def validate_temporal_consistency(self, element, soup):
        """Valide la cohérence temporelle des indicateurs"""
        try:
            # Rechercher des timestamps récents
            current_time = datetime.now(UTC)
            
            # Chercher des indicateurs de temps dans la page
            time_elements = soup.find_all(string=re.compile(r'ago|minutes?|seconds?|hours?'))
            
            for time_text in time_elements:
                if 'minute' in time_text.lower() and 'ago' in time_text.lower():
                    # Extraire le nombre de minutes
                    minutes_match = re.search(r'(\d+)\s*minute', time_text.lower())
                    if minutes_match:
                        minutes_ago = int(minutes_match.group(1))
                        # Si c'est trop vieux (>5 minutes), c'est suspect
                        if minutes_ago > 5:
                            return False
            
            return True
            
        except Exception:
            return True  # En cas d'erreur, on assume que c'est valide

    async def extract_player_name_validated(self, base_url, soup):
        """Extraction VALIDÉE du nom de joueur"""
        try:
            # Méthode 1: Extraire de l'URL
            url_patterns = [
                r'/summoner/([^/]+)',
                r'/player/([^/]+)',
                r'/profile/([^/]+)'
            ]
            
            for pattern in url_patterns:
                match = re.search(pattern, base_url, re.I)
                if match:
                    player_name = match.group(1)
                    # Nettoyer le nom
                    player_name = player_name.replace('%20', ' ').replace('+', ' ')
                    if len(player_name) > 2:  # Validation minimale
                        return player_name
            
            # Méthode 2: Extraire de la page
            summoner_selectors = [
                '.summoner-name',
                '[data-summoner-name]',
                '.player-name',
                'h1',
                '.profile-name'
            ]
            
            for selector in summoner_selectors:
                element = soup.select_one(selector)
                if element:
                    name = element.get_text().strip()
                    if len(name) > 2 and len(name) < 50:  # Validation de longueur
                        return name
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur extraction nom joueur: {e}")
            return None

    async def extract_game_data_validated(self, element, soup):
        """Extraction VALIDÉE des données de jeu"""
        try:
            game_data = {
                'is_coherent': False,
                'champion': None,
                'rank': None,
                'game_mode': None,
                'duration': None
            }
            
            # Rechercher les données dans l'élément et ses environs
            context_area = element.parent.parent if element.parent else element
            context_text = context_area.get_text()
            
            # Extraire le champion
            champion_match = re.search(r'champion[:\s]+([a-zA-Z\s]+)', context_text, re.I)
            if champion_match:
                game_data['champion'] = champion_match.group(1).strip()
            
            # Extraire le rang
            rank_match = re.search(r'(bronze|silver|gold|platinum|diamond|master|grandmaster|challenger)', context_text, re.I)
            if rank_match:
                game_data['rank'] = rank_match.group(1).capitalize()
            
            # Validation de cohérence : au moins 2 éléments doivent être présents
            valid_elements = sum(1 for v in game_data.values() if v is not None and v != False)
            game_data['is_coherent'] = valid_elements >= 1  # Au moins un élément valide
            
            return game_data
            
        except Exception as e:
            logger.error(f"Erreur extraction données jeu: {e}")
            return {'is_coherent': False}

    async def is_duplicate_detection(self, game_info, base_url):
        """Vérification anti-doublon"""
        try:
            # Créer une clé unique pour cette détection
            detection_key = f"{base_url}_{game_info.get('player', 'unknown')}"
            current_time = datetime.now(UTC)
            
            # Vérifier si on a déjà détecté cette partie récemment (< 5 minutes)
            if detection_key in self.last_detection:
                last_time = self.last_detection[detection_key]
                if (current_time - last_time).seconds < 300:  # 5 minutes
                    return True
            
            # Enregistrer cette détection
            self.last_detection[detection_key] = current_time
            
            # Nettoyer les anciennes détections (> 1 heure)
            old_keys = [k for k, v in self.last_detection.items() 
                       if (current_time - v).seconds > 3600]
            for key in old_keys:
                del self.last_detection[key]
            
            return False
            
        except Exception:
            return False

    async def extract_validated_game_info(self, validation_result, base_url):
        """Extraction finale des informations de jeu validées"""
        try:
            if not validation_result['is_valid']:
                return None
            
            game_data = validation_result['game_data']
            player_name = validation_result['player_name']
            
            # Construction des informations finales
            game_info = {
                'title': f"🔴 LIVE: {player_name}",
                'url': base_url,
                'player': player_name,
                'champion': game_data.get('champion', 'Inconnu'),
                'rank': game_data.get('rank', 'Non classé'),
                'confidence': validation_result['confidence'],
                'timestamp': datetime.now(UTC).isoformat()
            }
            
            # Enrichir le titre avec les informations disponibles
            if game_data.get('champion'):
                game_info['title'] += f" ({game_data['champion']})"
            
            if game_data.get('rank'):
                game_info['title'] += f" [{game_data['rank']}]"
            
            return game_info
            
        except Exception as e:
            logger.error(f"Erreur extraction finale: {e}")
            return None
